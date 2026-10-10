import os
import shutil
import sqlite3
import stat
import errno
import threading
import time
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing

import xxhash
from PySide6.QtCore import QObject, Signal

from core_scanner import canonical_directory, file_signature, is_link_stat, is_read_only
from ignore_rules import DEFAULT_IGNORE_TEXT, IgnoreRules, apply_ignore_rules, relative_path_key


class CopyManager(QObject):
    overall_progress = Signal(int, int)
    copy_finished = Signal()

    def __init__(self, db_path="sync_snapshot.db", max_workers=4):
        super().__init__()
        self.db_path = db_path
        self.max_workers = max(1, int(max_workers))
        self._progress_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self.is_syncing = False
        self.failed_count = 0
        self.errors = []
        self._target_roots = {}
        try:
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass

    @staticmethod
    def _is_covered_by_extra_dir(rel_path, extra_dirs):
        parent = relative_path_key(rel_path).rpartition("/")[0]
        while parent:
            if parent in extra_dirs:
                return True
            parent = parent.rpartition("/")[0]
        return False

    def start_sync(self, diff_results, mirror_mode=False, ignore_rules=None):
        if self.is_syncing:
            return
        self._cancel_event.clear()
        self.failed_count = 0
        self.errors = []
        self._target_roots.clear()
        self.ignore_rules = ignore_rules or IgnoreRules(global_lines=DEFAULT_IGNORE_TEXT.splitlines())
        self.mirror_mode = mirror_mode
        self.total_files = 0
        self.copied_count = 0
        self._last_progress = 0
        self.is_syncing = True
        self.worker_thread = threading.Thread(
            target=self._run_copy_queue,
            args=(diff_results,),
            name="data-synchronizer-copy",
            daemon=True,
        )
        self.worker_thread.start()

    def _prepare_diff_results(self, diff_results):
        diff_results = apply_ignore_rules(diff_results, self.ignore_rules, self._cancel_event)
        statuses = {"NEW", "MODIFIED"}
        if self.mirror_mode:
            statuses.update(("EXTRA", "EXTRA_DIR"))
        diff_results = [item for item in diff_results if item[0] in statuses]
        extra_dirs_by_pair = {}
        for item in diff_results:
            if item[0] == "EXTRA_DIR":
                pair_key = (item[4], item[5])
                extra_dirs_by_pair.setdefault(pair_key, set()).add(
                    relative_path_key(item[1])
                )

        filtered = []
        for item in diff_results:
            if self._cancel_event.is_set():
                return []
            status, rel_path = item[:2]
            if status in ("EXTRA", "EXTRA_DIR"):
                pair_key = (item[4], item[5])
                if self._is_covered_by_extra_dir(
                    rel_path, extra_dirs_by_pair.get(pair_key, ())
                ):
                    continue
            filtered.append(item)

        return sorted(filtered, key=lambda item: (item[6], item[1]))

    def _run_copy_queue(self, diff_results):
        db_operations = []
        try:
            self.diff_results = self._prepare_diff_results(diff_results)
            self.total_files = len(self.diff_results)
            self.overall_progress.emit(0, self.total_files)
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                items = iter(self.diff_results)
                pending = set()

                def submit_next():
                    if self._cancel_event.is_set():
                        return False
                    try:
                        item = next(items)
                    except StopIteration:
                        return False
                    pending.add(pool.submit(self._copy_single_file, item))
                    return True

                for _ in range(self.max_workers * 2):
                    if not submit_next():
                        break

                while pending:
                    completed, pending = wait(
                        pending, return_when=FIRST_COMPLETED
                    )
                    for future in completed:
                        operation = future.result()
                        if operation is not None:
                            db_operations.append(operation)
                        submit_next()

                    if len(db_operations) >= 1000:
                        self._apply_db_operations(db_operations)
                        db_operations.clear()

            if db_operations:
                self._apply_db_operations(db_operations)
        except Exception as exc:
            self._record_error("", exc)
        finally:
            self.is_syncing = False
            self.copy_finished.emit()

    def cancel(self):
        self._cancel_event.set()

    def wait_for_finished(self, timeout=3.0):
        worker = getattr(self, "worker_thread", None)
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def _advance_progress(self):
        with self._progress_lock:
            self.copied_count += 1
            current = self.copied_count
            now = time.monotonic()
            if current == self.total_files or now - self._last_progress >= 0.1:
                self._last_progress = now
                self.overall_progress.emit(current, self.total_files)

    def _record_error(self, path, exc):
        with self._progress_lock:
            self.failed_count += 1
            if len(self.errors) < 20:
                self.errors.append(f"{path}: {exc}" if path else str(exc))

    def _resume_offset(self, source_path, target_path, destination=None, hasher=None):
        """Only resume when the target is an exact prefix of the source."""
        with open(source_path, "rb") as source, open(target_path, "rb") as target:
            offset = 0
            while chunk := target.read(4 * 1024 * 1024):
                if self._cancel_event.is_set() or source.read(len(chunk)) != chunk:
                    return 0
                if destination is not None:
                    destination.write(chunk)
                if hasher is not None:
                    hasher.update(chunk)
                offset += len(chunk)
            return offset

    def _copy_single_file(self, item):
        status, rel_path, source_path, size, source_dir, target_dir, _ = item[:7]
        target_is_file = len(item) >= 8 and item[7]
        target_path = (
            target_dir
            if target_is_file
            else os.path.join(target_dir, rel_path)
        )
        normalized_rel = relative_path_key(rel_path)
        rules = self.ignore_rules.for_pair(source_dir, target_dir, target_is_file)

        try:
            if self._cancel_event.is_set():
                return None
            if status not in ("NEW", "MODIFIED", "EXTRA", "EXTRA_DIR") or rules.matches(
                rel_path, status == "EXTRA_DIR"
            ):
                return None
            if not target_is_file:
                # A directory replaced with a junction since scanning must not
                # redirect a write or deletion outside the configured target.
                root = self._target_roots.get(target_dir)
                if root is None:
                    root = self._target_roots.setdefault(target_dir, os.path.realpath(target_dir))
                resolved_target = os.path.normcase(os.path.normpath(os.path.join(root, rel_path)))
                if os.path.normcase(os.path.realpath(target_path)) != resolved_target:
                    raise OSError(f"Target path contains a link: {target_path}")
            else:
                resolved_target = os.path.normcase(os.path.realpath(target_path))
            try:
                target_stat = os.lstat(target_path)
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None and is_link_stat(target_stat) and status != "EXTRA_DIR":
                raise OSError(f"Target is a link: {target_path}")
            if target_stat is not None and not stat.S_ISDIR(target_stat.st_mode) and is_read_only(target_stat):
                raise PermissionError(f"Target is read-only: {target_path}")
            if status in ("EXTRA", "EXTRA_DIR"):
                if not self.mirror_mode:
                    return None
                if status == "EXTRA_DIR":
                    if os.path.exists(target_path) and not self._remove_extra_directory(
                        target_path, rel_path, rules
                    ):
                        return None
                    return (
                        "delete_tree",
                        normalized_rel,
                        source_dir,
                        target_dir,
                    )

                if os.path.exists(target_path):
                    os.remove(target_path)
                return (
                    "delete",
                    normalized_rel,
                    source_dir,
                    target_dir,
                )

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            copied = self._copy_file(source_path, target_path, size, target_stat, resolved_target)
            if copied is None:
                return None
            copied_stat, file_hash = copied
            return (
                "upsert",
                normalized_rel,
                source_dir,
                target_dir,
                copied_stat.st_size,
                copied_stat.st_mtime,
                file_hash,
            )
        except Exception as exc:
            self._record_error(rel_path, exc)
            return None
        finally:
            self._advance_progress()

    def _copy_file(self, source_path, target_path, size, target_stat, resolved_target):
        """Stage a complete, stable file before replacing the destination."""
        temporary_path = None
        try:
            with open(source_path, "rb") as src:
                source_stat = os.fstat(src.fileno())
                if source_stat.st_size != size:
                    raise OSError(f"Source size changed since scan: {source_path}")
                with tempfile.NamedTemporaryFile(
                    mode="w+b", dir=os.path.dirname(target_path),
                    prefix=".ds-sync-", suffix=".tmp", delete=False,
                ) as dst:
                    temporary_path = dst.name
                    hasher = xxhash.xxh64()
                    offset = 0
                    if target_stat is not None and target_stat.st_size < size:
                        offset = self._resume_offset(source_path, target_path, dst, hasher)
                    if not offset:
                        dst.seek(0)
                        dst.truncate()
                        hasher = xxhash.xxh64()
                    src.seek(offset)
                    while True:
                        if self._cancel_event.is_set():
                            return None
                        chunk = src.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        hasher.update(chunk)
                        dst.write(chunk)
                    if file_signature(os.fstat(src.fileno())) != file_signature(source_stat):
                        raise OSError(f"Source changed during copy: {source_path}")
                if file_signature(os.stat(source_path)) != file_signature(source_stat):
                    raise OSError(f"Source changed during copy: {source_path}")
            if self._cancel_event.is_set():
                return None
            # Recheck the target before committing a staged copy. A new target,
            # changed contents or new read-only protection requires a new scan.
            try:
                current_target = os.lstat(target_path)
            except FileNotFoundError:
                current_target = None
            if (
                os.path.normcase(os.path.realpath(target_path)) != resolved_target
                or (current_target is None) != (target_stat is None)
                or current_target is not None and (
                    is_link_stat(current_target) or is_read_only(current_target)
                    or file_signature(current_target) != file_signature(target_stat)
                )
            ):
                raise OSError(f"Target changed during copy: {target_path}")
            shutil.copystat(source_path, temporary_path)
            if self._cancel_event.is_set():
                return None
            os.replace(temporary_path, target_path)
            return source_stat, hasher.hexdigest()
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except PermissionError:
                    # Only this operation's temporary file may need cleanup.
                    os.chmod(temporary_path, stat.S_IWRITE)
                    os.unlink(temporary_path)

    def _remove_extra_directory(self, path, rel_path, rules=None):
        """Check rules again while deleting, including files added since scan."""
        rules = rules if rules is not None else self.ignore_rules
        if self._cancel_event.is_set() or rules.matches(rel_path, True):
            return False
        # Do not descend into Windows junctions or other directory links.
        path_stat = os.lstat(path)
        if stat.S_ISLNK(path_stat.st_mode) or (
            getattr(path_stat, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            if os.name == "nt":
                os.rmdir(path)
            else:
                os.unlink(path)
            return True
        with os.scandir(path) as entries:
            children = list(entries)
        for entry in children:
            if self._cancel_event.is_set():
                return False
            child_rel = os.path.join(rel_path, entry.name)
            is_directory = entry.is_dir(follow_symlinks=False)
            if rules.matches(child_rel, is_directory):
                continue
            if is_directory:
                self._remove_extra_directory(entry.path, child_rel, rules)
            else:
                if is_read_only(entry.stat(follow_symlinks=False)):
                    continue
                os.remove(entry.path)
        if self._cancel_event.is_set():
            return False
        try:
            try:
                os.rmdir(path)
            except PermissionError:
                os.chmod(path, stat.S_IWRITE)
                os.rmdir(path)
            return True
        except OSError as exc:
            if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                return False
            raise

    def _apply_db_operations(self, operations):
        if not operations:
            return

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("PRAGMA synchronous=NORMAL")
            batches = {"upsert": [], "delete": [], "delete_tree": []}
            canonical_pairs = {}
            for operation in operations:
                kind = operation[0]
                if kind not in batches:
                    continue
                pair = operation[2:4]
                if pair not in canonical_pairs:
                    canonical_pairs[pair] = tuple(canonical_directory(path) for path in pair)
                values = (relative_path_key(operation[1]), *canonical_pairs[pair])
                if kind == "upsert":
                    values += operation[4:]
                batches[kind].append(values)
            upserts, deletes, delete_trees = (batches[kind] for kind in ("upsert", "delete", "delete_tree"))

            if upserts:
                conn.executemany(
                    """
                    INSERT INTO file_snapshot
                        (path, src_dir, dst_dir, size, mtime, file_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path, src_dir, dst_dir) DO UPDATE SET
                        size=excluded.size,
                        mtime=excluded.mtime,
                        file_hash=excluded.file_hash
                    """,
                    upserts,
                )
            if deletes:
                conn.executemany(
                    """
                    DELETE FROM file_snapshot
                    WHERE path=? AND src_dir=? AND dst_dir=?
                    """,
                    deletes,
                )
            for rel_path, source_dir, target_dir in delete_trees:
                conn.execute(
                    """
                    DELETE FROM file_snapshot
                    WHERE (path=? OR substr(path, 1, ?)=?)
                      AND src_dir=? AND dst_dir=?
                    """,
                    (
                        rel_path,
                        len(rel_path + "/"),
                        rel_path + "/",
                        source_dir,
                        target_dir,
                    ),
                )
