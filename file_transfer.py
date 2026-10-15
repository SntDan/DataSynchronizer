"""Windows copy acceleration and exclusive ownership of resumable files."""

import os
import ctypes
import stat
import threading
from contextlib import contextmanager


class CopyCancellation(threading.Event):
    """One cancellation signal shared by Python loops and the Windows API."""

    def __init__(self):
        super().__init__()
        self.native_flag = ctypes.c_int(0)

    def set(self):
        super().set()
        self.native_flag.value = 1

    def clear(self):
        self.native_flag.value = 0
        super().clear()


@contextmanager
def lock_partial(path):
    with open(path, "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    # Windows prevents deleting a lock opened by another process. POSIX allows
    # that, so leave its lock file in place to keep a stable lock identity.
    if os.name == "nt":
        try:
            os.unlink(path)
        except (FileNotFoundError, PermissionError):
            pass


copy_file_native = None


def can_resume_stream(path):
    return True


def replace_file(source, target, target_stat, cancel_event):
    """Commit a staged copy; only temporarily relax a Windows read-only flag."""
    if cancel_event.is_set():
        return False
    read_only = target_stat is not None and (
        getattr(target_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0)
    )
    if read_only:
        os.chmod(target, stat.S_IWRITE)
    committed = False
    try:
        if cancel_event.is_set():
            return False
        if read_only:
            current = os.lstat(target)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
            if any(getattr(current, field) != getattr(target_stat, field) for field in fields):
                raise OSError(f"Target changed before replacement: {target}")
        os.replace(source, target)
        committed = True
        return True
    finally:
        if read_only and not committed:
            try:
                current = os.lstat(target)
            except FileNotFoundError:
                current = None
            if current is not None and (
                current.st_dev, current.st_ino
            ) == (target_stat.st_dev, target_stat.st_ino):
                # A different file may have appeared at this name. Restore
                # only the original target, without altering any other flags.
                try:
                    os.chmod(target, stat.S_IREAD)
                except OSError as exc:
                    raise OSError(f"Could not restore read-only target {target}: {exc}") from exc


if os.name == "nt":
    from ctypes import wintypes

    _PROGRESS = ctypes.WINFUNCTYPE(
        wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong,
        ctypes.c_longlong, ctypes.c_longlong, wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE, wintypes.HANDLE, wintypes.LPVOID,
    )
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _copy_file_ex = _kernel32.CopyFileExW
    _copy_file_ex.argtypes = (
        wintypes.LPCWSTR, wintypes.LPCWSTR, _PROGRESS, wintypes.LPVOID,
        ctypes.POINTER(wintypes.BOOL), wintypes.DWORD,
    )
    _copy_file_ex.restype = wintypes.BOOL

    class _StreamData(ctypes.Structure):
        _fields_ = [("size", ctypes.c_longlong), ("name", wintypes.WCHAR * 296)]

    _find_first_stream = _kernel32.FindFirstStreamW
    _find_first_stream.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_StreamData), wintypes.DWORD)
    _find_first_stream.restype = wintypes.HANDLE
    _find_next_stream = _kernel32.FindNextStreamW
    _find_next_stream.argtypes = (wintypes.HANDLE, ctypes.POINTER(_StreamData))
    _find_next_stream.restype = wintypes.BOOL
    _find_close = _kernel32.FindClose
    _find_close.argtypes = (wintypes.HANDLE,)
    _find_close.restype = wintypes.BOOL

    def _long_path(path):
        path = os.path.abspath(path)
        if path.startswith("\\\\?\\"):
            return path
        return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path

    def can_resume_stream(path):
        # A Python prefix resume only copies the main stream. Files with named
        # streams use a full native copy so those streams are never incomplete.
        data = _StreamData()
        handle = _find_first_stream(_long_path(path), 0, ctypes.byref(data), 0)
        if handle == ctypes.c_void_p(-1).value:
            return False  # Includes filesystems that cannot enumerate streams.
        try:
            if data.name != "::$DATA" or _find_next_stream(handle, ctypes.byref(data)):
                return False
            return ctypes.get_last_error() == 38  # ERROR_HANDLE_EOF
        finally:
            _find_close(handle)

    def copy_file_native(source, target, cancel_event, *, keep_partial=False):
        """Copy to an existing, pinned temporary file; return completion/bytes/error."""
        written = 0

        if cancel_event.is_set():
            return False, 0, None
        flag = getattr(cancel_event, "native_flag", None)
        cancel_pointer = ctypes.cast(ctypes.byref(flag), ctypes.POINTER(wintypes.BOOL)) if flag is not None else None
        # Also report byte deltas for live speed sampling during large copies.
        report_bytes = getattr(cancel_event, "on_bytes_copied", None)
        last_transferred = 0
        callback = _PROGRESS()
        if keep_partial or flag is None or report_bytes is not None:
            @_PROGRESS
            def callback(total, transferred, stream_size, stream_bytes, stream,
                         reason, source_handle, target_handle, context):
                nonlocal written, last_transferred
                if report_bytes is not None and transferred > last_transferred:
                    report_bytes(transferred - last_transferred)
                    last_transferred = transferred
                if stream == 1:
                    written = stream_bytes
                # STOP retains the partial file. RESTARTABLE is deliberately
                # not used: repeated flushes would penalize ordinary copies.
                return 2 if cancel_event.is_set() else 0
        completed = _copy_file_ex(
            _long_path(source), _long_path(target), callback, None, cancel_pointer, 0,
        )
        if completed:
            return True, written, None
        error = ctypes.get_last_error()
        if error == 1235 and cancel_event.is_set():
            return False, written, None
        return False, written, ctypes.WinError(error)
