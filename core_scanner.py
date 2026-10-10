import os
import sqlite3
import stat
from contextlib import closing

import xxhash
from PySide6.QtCore import QObject, Signal

from ignore_rules import DEFAULT_IGNORE_TEXT, IgnoreRules


def canonical_directory(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_directory_link(entry, is_directory):
    # Preserve links without traversing outside the configured path pair.
    return entry.is_symlink() or (
        is_directory
        and getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


class SyncScanner(QObject):
    progress_updated = Signal(int, int)
    diff_batch_found = Signal(list)

    def __init__(self, db_path="sync_snapshot.db", ignore_rules=None):
        super().__init__()
        self.db_path = db_path
        self.ignore_rules = ignore_rules or IgnoreRules(DEFAULT_IGNORE_TEXT.splitlines())
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
            self._canonicalize_snapshot_directories(conn)

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
    def _canonicalize_snapshot_directories(conn):
        groups = conn.execute(
            "SELECT DISTINCT src_dir, dst_dir FROM file_snapshot"
        ).fetchall()
        if all(
            src_dir == canonical_directory(src_dir)
            and dst_dir == canonical_directory(dst_dir)
            for src_dir, dst_dir in groups
        ):
            return

        rows = conn.execute(
            """
            SELECT path, src_dir, dst_dir, size, mtime, file_hash
            FROM file_snapshot
            """
        ).fetchall()
        rows.sort(
            key=lambda row: (
                row[1] == canonical_directory(row[1])
                and row[2] == canonical_directory(row[2])
            )
        )
        conn.execute("DELETE FROM file_snapshot")
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
            [
                (
                    path,
                    canonical_directory(src_dir),
                    canonical_directory(dst_dir),
                    size,
                    mtime,
                    file_hash,
                )
                for path, src_dir, dst_dir, size, mtime, file_hash in rows
            ],
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
        target_is_file=False,
    ):
        is_cancelled = (
            cancel_event.is_set if cancel_event is not None else lambda: False
        )
        snapshots = {}
        snapshot_source = canonical_directory(source_dir)
        snapshot_target = canonical_directory(target_dir)
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT path, size, mtime, file_hash
                FROM file_snapshot
                WHERE src_dir=? AND dst_dir=?
                """,
                (snapshot_source, snapshot_target),
            )
            snapshots = {
                row[0]: (row[1], row[2], row[3]) for row in cursor
            }

        differences = []
        scanned_count = 0
        source_files = set()
        source_dirs = set()
        extra_directories = []
        protected_dirs = set()
        separator = os.sep

        def protect_parents(rel_path):
            parent = rel_path.rpartition(separator)[0]
            while parent:
                protected_dirs.add(parent)
                parent = parent.rpartition(separator)[0]

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
                    target_is_file,
                )
            )
            if len(differences) >= 1000:
                self.diff_batch_found.emit(list(differences))
                differences.clear()

        def compare_source_file(source_path, rel_path, source_stat):
            nonlocal scanned_count
            size = source_stat.st_size
            mtime = source_stat.st_mtime
            source_files.add(rel_path)
            if self.ignore_rules.matches(rel_path):
                add_difference("IGNORED", rel_path, source_path, size)
                scanned_count += 1
                return
            target_path = (
                target_dir
                if target_is_file
                else os.path.join(target_dir, rel_path)
            )
            snapshot = snapshots.get(rel_path.replace("\\", "/"))
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
                        or self.get_file_hash(source_path) != snap_hash
                    ):
                        status = "MODIFIED"
                else:
                    try:
                        if os.stat(target_path).st_size != size:
                            status = "MODIFIED"
                    except OSError:
                        status = "NEW"

            if status:
                add_difference(status, rel_path, source_path, size)

            scanned_count += 1
            if scanned_count % 500 == 0:
                self.progress_updated.emit(scanned_count, 0)

        source_is_directory = os.path.isdir(source_dir)

        if source_is_directory:
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
                            is_directory = entry.is_dir(follow_symlinks=False)
                            is_link = is_directory_link(entry, is_directory)
                            if is_link:
                                is_directory = is_directory or entry.is_dir()

                            if is_link or self.ignore_rules.matches(rel_path, is_directory):
                                if is_directory:
                                    source_dirs.add(rel_path)
                                else:
                                    source_files.add(rel_path)
                                try:
                                    size = 0 if is_directory else entry.stat(
                                        follow_symlinks=False
                                    ).st_size
                                except OSError:
                                    size = 0
                                add_difference(
                                    "IGNORED_DIR" if is_directory else "IGNORED",
                                    rel_path, entry.path, size,
                                )
                                scanned_count += 1
                                continue
                            if is_directory:
                                source_dirs.add(rel_path)
                                stack.append((entry.path, rel_path))
                                continue
                            source_stat = entry.stat(follow_symlinks=False)

                            compare_source_file(
                                entry.path, rel_path, source_stat
                            )
                except OSError as exc:
                    raise OSError(f"Could not scan {current_path}: {exc}") from exc

        elif os.path.isfile(source_dir):
            compare_source_file(
                source_dir,
                os.path.basename(source_dir),
                os.stat(source_dir),
            )

        # A single-file pair only owns its same-named target file. It must not
        # treat unrelated contents of the target directory as mirror extras.
        if (
            source_is_directory
            and not target_is_file
            and os.path.isdir(target_dir)
        ):
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
                                is_link = is_directory_link(entry, is_directory)
                                if is_link:
                                    is_directory = is_directory or entry.is_dir()
                            except OSError:
                                continue

                            if is_link or self.ignore_rules.matches(rel_path, is_directory):
                                protect_parents(rel_path)
                                if is_link or (rel_path not in source_dirs and rel_path not in source_files):
                                    try:
                                        size = 0 if is_directory else entry.stat(
                                            follow_symlinks=False
                                        ).st_size
                                    except OSError:
                                        size = 0
                                    add_difference(
                                        "IGNORED_DIR" if is_directory else "IGNORED",
                                        rel_path, entry.path, size,
                                    )
                                continue
                            if is_directory:
                                if rel_path not in source_dirs:
                                    extra_directories.append((rel_path, entry.path))
                                stack.append((entry.path, rel_path))
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
                    protected_dirs.add(current_rel)
                    protect_parents(current_rel)
                    continue

        for rel_path, abs_path in extra_directories:
            if is_cancelled():
                return
            add_difference(
                "PRESERVED_DIR" if rel_path in protected_dirs else "EXTRA_DIR",
                rel_path, abs_path, 0,
            )
        if differences:
            self.diff_batch_found.emit(differences)
        self.progress_updated.emit(scanned_count, 0)
