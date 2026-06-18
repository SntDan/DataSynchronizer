import os
import shutil
import sqlite3
import stat
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing

import xxhash
from PySide6.QtCore import QObject, Signal

from core_scanner import canonical_directory


class CopyManager(QObject):
    overall_progress = Signal(int, int)
    current_file_progress = Signal(str, int)
    copy_finished = Signal()

    def __init__(self, db_path="sync_snapshot.db", max_workers=4):
        super().__init__()
        self.db_path = db_path
        self.max_workers = max(1, int(max_workers))
        self._progress_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self.is_syncing = False
        try:
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass

    @staticmethod
    def _get_file_hash(filepath):
        hasher = xxhash.xxh64()
        try:
            with open(filepath, "rb") as file_obj:
                while chunk := file_obj.read(4 * 1024 * 1024):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _is_covered_by_extra_dir(rel_path, extra_dirs):
        parent = rel_path.replace("\\", "/").rpartition("/")[0]
        while parent:
            if parent in extra_dirs:
                return True
            parent = parent.rpartition("/")[0]
        return False

    def start_sync(self, diff_results, mirror_mode=False):
        self._cancel_event.clear()
        extra_dirs_by_pair = {}
        for item in diff_results:
            if item[0] == "EXTRA_DIR":
                pair_key = (item[4], item[5])
                extra_dirs_by_pair.setdefault(pair_key, set()).add(
                    item[1].replace("\\", "/")
                )

        filtered = []
        for item in diff_results:
            status, rel_path = item[:2]
            if status in ("EXTRA", "EXTRA_DIR"):
                pair_key = (item[4], item[5])
                if self._is_covered_by_extra_dir(
                    rel_path, extra_dirs_by_pair.get(pair_key, ())
                ):
                    continue
            filtered.append(item)

        self.diff_results = sorted(
            filtered, key=lambda item: (item[6], item[1])
        )
        self.mirror_mode = mirror_mode
        self.total_files = len(self.diff_results)
        self.copied_count = 0
        self.is_syncing = True
        self.worker_thread = threading.Thread(
            target=self._run_copy_queue,
            name="data-synchronizer-copy",
            daemon=True,
        )
        self.worker_thread.start()

    def _run_copy_queue(self):
        db_operations = []
        try:
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
        self.overall_progress.emit(current, self.total_files)

    @staticmethod
    def _remove_readonly(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    def _copy_single_file(self, item):
        status, rel_path, source_path, size, source_dir, target_dir, _ = item
        target_path = os.path.join(target_dir, rel_path)
        normalized_rel = rel_path.replace("\\", "/")

        try:
            if self._cancel_event.is_set():
                return None
            if status in ("EXTRA", "EXTRA_DIR"):
                if not self.mirror_mode:
                    return None
                if status == "EXTRA_DIR":
                    if os.path.exists(target_path):
                        shutil.rmtree(
                            target_path, onerror=self._remove_readonly
                        )
                    return (
                        "delete_tree",
                        normalized_rel,
                        source_dir,
                        target_dir,
                    )

                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except OSError:
                        os.chmod(target_path, stat.S_IWRITE)
                        os.remove(target_path)
                return (
                    "delete",
                    normalized_rel,
                    source_dir,
                    target_dir,
                )

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            copied_bytes = 0
            mode = "wb"

            if os.path.exists(target_path):
                existing_size = os.path.getsize(target_path)
                if existing_size < size:
                    copied_bytes = existing_size
                    mode = "ab"
                elif existing_size == size and status != "MODIFIED":
                    return (
                        "upsert",
                        normalized_rel,
                        source_dir,
                        target_dir,
                        size,
                        os.path.getmtime(source_path),
                        self._get_file_hash(source_path),
                    )

            hasher = xxhash.xxh64()
            inline_hash = copied_bytes == 0
            last_percent = -1
            with open(source_path, "rb") as src, open(
                target_path, mode
            ) as dst:
                src.seek(copied_bytes)
                while chunk := src.read(4 * 1024 * 1024):
                    if self._cancel_event.is_set():
                        return None
                    if inline_hash:
                        hasher.update(chunk)
                    dst.write(chunk)
                    copied_bytes += len(chunk)
                    if size:
                        percent = copied_bytes * 100 // size
                        if percent != last_percent:
                            self.current_file_progress.emit(
                                rel_path, percent
                            )
                            last_percent = percent

            shutil.copystat(source_path, target_path)
            file_hash = (
                hasher.hexdigest()
                if inline_hash
                else self._get_file_hash(source_path)
            )
            return (
                "upsert",
                normalized_rel,
                source_dir,
                target_dir,
                size,
                os.path.getmtime(source_path),
                file_hash,
            )
        except Exception as exc:
            print(f"Error processing {rel_path}: {exc}")
            return None
        finally:
            self._advance_progress()

    def _apply_db_operations(self, operations):
        if not operations:
            return

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("PRAGMA synchronous=NORMAL")
            upserts = [
                (
                    op[1],
                    canonical_directory(op[2]),
                    canonical_directory(op[3]),
                    *op[4:],
                )
                for op in operations
                if op[0] == "upsert"
            ]
            deletes = [
                (
                    op[1],
                    canonical_directory(op[2]),
                    canonical_directory(op[3]),
                )
                for op in operations
                if op[0] == "delete"
            ]
            delete_trees = [
                (
                    op[1],
                    canonical_directory(op[2]),
                    canonical_directory(op[3]),
                )
                for op in operations
                if op[0] == "delete_tree"
            ]

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
                    WHERE (path=? OR path LIKE ?)
                      AND src_dir=? AND dst_dir=?
                    """,
                    (
                        rel_path,
                        rel_path + "/%",
                        source_dir,
                        target_dir,
                    ),
                )
