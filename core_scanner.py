import os
import sqlite3
from contextlib import closing

import xxhash
from PySide6.QtCore import QObject, Signal


IGNORED_FILENAMES = {
    "Thumbs.db",
    "thumbs.db",
    "desktop.ini",
    "Desktop.ini",
    ".DS_Store",
    "$RECYCLE.BIN",
}


class SyncScanner(QObject):
    progress_updated = Signal(int, int)
    diff_batch_found = Signal(list)

    def __init__(self, db_path="sync_snapshot.db"):
        super().__init__()
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.DatabaseError:
                pass

            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(file_snapshot)")
            }
            needs_rebuild = (
                columns
                and ("src_dir" not in columns or "dst_dir" not in columns)
            )

            if needs_rebuild:
                conn.execute(
                    "ALTER TABLE file_snapshot RENAME TO file_snapshot_old"
                )
                self._create_snapshot_table(conn)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO file_snapshot
                        (path, src_dir, dst_dir, size, mtime, file_hash)
                    SELECT path, '', '', size, mtime, file_hash
                    FROM file_snapshot_old
                    """
                )
                conn.execute("DROP TABLE file_snapshot_old")
            else:
                self._create_snapshot_table(conn)

    @staticmethod
    def _create_snapshot_table(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_snapshot (
                path TEXT,
                src_dir TEXT NOT NULL DEFAULT '',
                dst_dir TEXT NOT NULL DEFAULT '',
                size INTEGER,
                mtime REAL,
                file_hash TEXT,
                PRIMARY KEY (path, src_dir, dst_dir)
            )
            """
        )

    @staticmethod
    def get_file_hash(filepath):
        hasher = xxhash.xxh64()
        try:
            with open(filepath, "rb") as file_obj:
                while chunk := file_obj.read(4 * 1024 * 1024):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return None

    def scan_and_compare(
        self,
        source_dir,
        target_dir,
        use_deep_hash=False,
        pair_index=0,
        cancel_event=None,
    ):
        is_cancelled = (
            cancel_event.is_set if cancel_event is not None else lambda: False
        )
        snapshots = {}
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT path, size, mtime, file_hash
                FROM file_snapshot
                WHERE src_dir=? AND dst_dir=?
                """,
                (source_dir, target_dir),
            )
            snapshots = {
                row[0]: (row[1], row[2], row[3]) for row in cursor
            }

        differences = []
        scanned_count = 0
        source_files = set()
        source_dirs = set()
        separator = os.sep

        def add_difference(status, rel_path, abs_path, size):
            differences.append(
                (
                    status,
                    rel_path,
                    abs_path,
                    size,
                    source_dir,
                    target_dir,
                    pair_index,
                )
            )
            if len(differences) >= 1000:
                self.diff_batch_found.emit(list(differences))
                differences.clear()

        if os.path.isdir(source_dir):
            stack = [(source_dir, "")]
            while stack:
                if is_cancelled():
                    return
                current_path, current_rel = stack.pop()
                try:
                    with os.scandir(current_path) as entries:
                        for entry in entries:
                            if is_cancelled():
                                return
                            rel_path = (
                                current_rel + separator + entry.name
                                if current_rel
                                else entry.name
                            )
                            try:
                                is_directory = entry.is_dir(
                                    follow_symlinks=False
                                )
                            except OSError:
                                continue

                            if is_directory:
                                source_dirs.add(rel_path)
                                stack.append((entry.path, rel_path))
                                continue
                            if entry.name in IGNORED_FILENAMES:
                                continue

                            try:
                                source_stat = entry.stat(
                                    follow_symlinks=False
                                )
                            except OSError:
                                continue

                            size = source_stat.st_size
                            mtime = source_stat.st_mtime
                            source_files.add(rel_path)
                            target_path = os.path.join(target_dir, rel_path)
                            snapshot = snapshots.get(
                                rel_path.replace("\\", "/")
                            )
                            status = None

                            if snapshot is None:
                                try:
                                    target_stat = os.stat(target_path)
                                    if (
                                        target_stat.st_size != size
                                        or target_stat.st_mtime < mtime
                                    ):
                                        status = "MODIFIED"
                                except OSError:
                                    status = "NEW"
                            else:
                                snap_size, snap_mtime, snap_hash = snapshot
                                if snap_size != size or snap_mtime != mtime:
                                    if (
                                        not use_deep_hash
                                        or self.get_file_hash(entry.path)
                                        != snap_hash
                                    ):
                                        status = "MODIFIED"
                                else:
                                    try:
                                        if os.stat(target_path).st_size != size:
                                            status = "MODIFIED"
                                    except OSError:
                                        status = "NEW"

                            if status:
                                add_difference(
                                    status, rel_path, entry.path, size
                                )

                            scanned_count += 1
                            if scanned_count % 500 == 0:
                                self.progress_updated.emit(scanned_count, 0)
                except OSError:
                    continue

        if os.path.isdir(target_dir):
            stack = [(target_dir, "")]
            while stack:
                if is_cancelled():
                    return
                current_path, current_rel = stack.pop()
                try:
                    with os.scandir(current_path) as entries:
                        for entry in entries:
                            if is_cancelled():
                                return
                            rel_path = (
                                current_rel + separator + entry.name
                                if current_rel
                                else entry.name
                            )
                            try:
                                is_directory = entry.is_dir(
                                    follow_symlinks=False
                                )
                            except OSError:
                                continue

                            if is_directory:
                                if rel_path not in source_dirs:
                                    add_difference(
                                        "EXTRA_DIR", rel_path, entry.path, 0
                                    )
                                    # One parent entry is enough for mirror deletion.
                                    # Skipping its subtree avoids a potentially huge
                                    # second traversal of data absent from the source.
                                    continue
                                stack.append((entry.path, rel_path))
                                continue
                            if entry.name in IGNORED_FILENAMES:
                                continue

                            if rel_path not in source_files:
                                try:
                                    size = entry.stat(
                                        follow_symlinks=False
                                    ).st_size
                                except OSError:
                                    size = 0
                                add_difference(
                                    "EXTRA", rel_path, entry.path, size
                                )

                            scanned_count += 1
                            if scanned_count % 500 == 0:
                                self.progress_updated.emit(scanned_count, 0)
                except OSError:
                    continue

        if differences:
            self.diff_batch_found.emit(differences)
        self.progress_updated.emit(scanned_count, 0)
