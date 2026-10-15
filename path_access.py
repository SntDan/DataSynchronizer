"""Strict path checks and bounded, cancellable connection validation."""

import os
import stat
import threading
import time
from concurrent.futures import CancelledError


ACCESS_TIMEOUT = 5.0
# A timed-out OS call cannot always be interrupted. Bound abandoned probes,
# keep them read-only, and never let them emit scan results or touch the UI.
_probe_slots = threading.BoundedSemaphore(2)


def check_missing_error(error):
    if getattr(error, "winerror", None) not in (None, 2, 3):
        raise error


def inspect_target(path):
    """Return target stat and a reachable directory guarding a missing target."""
    target = candidate = os.path.abspath(path)
    while True:
        try:
            info = os.stat(candidate)
        except FileNotFoundError as exc:
            check_missing_error(exc)
            parent = os.path.dirname(candidate)
            if parent == candidate:
                raise
            candidate = parent
            continue
        if candidate != target:
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(candidate)
            return None, candidate
        return info, candidate if stat.S_ISDIR(info.st_mode) else os.path.dirname(candidate)


def require_readable_directory(path):
    # stat/isdir alone can use cached metadata on a disconnected network drive.
    with os.scandir(path) as entries:
        next(entries, None)


def run_access_check(check, cancel_event, description, timeout=None):
    timeout = ACCESS_TIMEOUT if timeout is None else timeout
    if cancel_event.is_set():
        raise CancelledError()
    if not _probe_slots.acquire(blocking=False):
        raise OSError("Previous path access checks are still pending; retry later.")
    done = threading.Event()
    result = {}

    def probe():
        try:
            result["value"] = check()
        except Exception as exc:
            result["error"] = exc
        finally:
            _probe_slots.release()
            done.set()

    worker = threading.Thread(target=probe, name="path-access-check", daemon=True)
    try:
        worker.start()
    except Exception:
        _probe_slots.release()
        raise
    deadline = time.monotonic() + timeout
    while not done.wait(min(0.05, max(0, deadline - time.monotonic()))):
        if cancel_event.is_set():
            raise CancelledError()
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Path access check timed out after {timeout:g}s:\n{description}")
    if cancel_event.is_set():
        raise CancelledError()
    if "error" in result:
        raise result["error"]
    return result["value"]
