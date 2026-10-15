import os
import sqlite3
import stat
import time
from contextlib import closing

import xxhash
from PySide6.QtCore import QObject, Signal

from ignore_rules import DEFAULT_IGNORE_TEXT, IgnoreRules, relative_path_key


def canonical_directory(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_directory_link(entry, is_directory):
    # Preserve links without traversing outside the configured path pair.
    return entry.is_symlink() or (
        is_directory and is_link_stat(entry.stat(follow_symlinks=False))
    )


def is_link_stat(file_stat):
    return stat.S_ISLNK(file_stat.st_mode) or (
        stat.S_ISDIR(file_stat.st_mode)
        and getattr(file_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def is_read_only(file_stat):
    return bool(
        getattr(file_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0)
    )


def file_signature(file_stat):
    result = (
        file_stat.st_size, file_stat.st_mtime_ns,
        file_stat.st_dev, file_stat.st_ino,
    )
    # Windows change times can update on opening a recently written file;
    # they cannot reliably identify a content change here.
    return result if os.name == "nt" else result + (file_stat.st_ctime_ns,)


class SyncScanner(QObject):
    progress_updated = Signal(int)
    diff_batch_found = Signal(list)
    file_check_started = Signal(str)

    def __init__(self, db_path="sync_snapshot.db", ignore_rules=None):
        super().__init__()
        self.db_path = db_path
        self.ignore_rules = ignore_rules or IgnoreRules(global_lines=DEFAULT_IGNORE_TEXT.splitlines())
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS snapshot_pair ON file_snapshot(src_dir, dst_dir)"
            )

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
        canonical_pairs = {
            (source, target): (canonical_directory(source), canonical_directory(target))
            for source, target in groups
        }
        if all(pair == canonical for pair, canonical in canonical_pairs.items()):
            return

        rows = conn.execute(
            """
            SELECT path, src_dir, dst_dir, size, mtime, file_hash
            FROM file_snapshot
            """
        ).fetchall()
        rows.sort(
            key=lambda row: (
                (row[1], row[2]) == canonical_pairs[(row[1], row[2])]
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
            (
                (
                    path,
                    *canonical_pairs[(src_dir, dst_dir)],
                    size,
                    mtime,
                    file_hash,
                )
                for path, src_dir, dst_dir, size, mtime, file_hash in rows
            ),
        )

    @staticmethod
    def get_file_hash(filepath, cancel_event=None, expected_stat=None):
        """Read current contents; fail if the file changes during verification."""
        is_cancelled = cancel_event.is_set if cancel_event is not None else lambda: False
        if is_cancelled():
            return None
        hasher = xxhash.xxh64()
        with open(filepath, "rb") as file_obj:
            before = os.fstat(file_obj.fileno())
            if expected_stat is not None and file_signature(before) != file_signature(expected_stat):
                raise OSError(f"File changed before verification: {filepath}")
            while True:
                if is_cancelled():
                    return None
                chunk = file_obj.read(4 * 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            if file_signature(os.fstat(file_obj.fileno())) != file_signature(before):
                raise OSError(f"File changed during verification: {filepath}")
        if file_signature(os.stat(filepath)) != file_signature(before):
            raise OSError(f"File changed during verification: {filepath}")
        return hasher.hexdigest()

    def scan_and_compare(
        self,
        source_dir,
        target_dir,
        pair_index=0,
        cancel_event=None,
        target_is_file=False,
        verify_contents=False,
    ):
        is_cancelled = (
            cancel_event.is_set if cancel_event is not None else lambda: False
        )
        rules = self.ignore_rules.for_pair(source_dir, target_dir, target_is_file)
        snapshots = {}
        if not verify_contents:
            with closing(sqlite3.connect(self.db_path)) as conn:
                snapshots = {
                    relative_path_key(path): (size, mtime)
                    for path, size, mtime in conn.execute(
                        "SELECT path, size, mtime FROM file_snapshot WHERE src_dir=? AND dst_dir=?",
                        (canonical_directory(source_dir), canonical_directory(target_dir)),
                    )
                }
        differences = []
        scanned_count = 0
        last_progress = 0
        source_files = set()
        source_dirs = set()
        extra_directories = []
        protected_dirs = set()
        separator = os.sep

        def report_progress(rel_path=None):
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress >= 0.1:
                last_progress = now
                if rel_path is not None:
                    self.file_check_started.emit(rel_path)
                else:
                    self.progress_updated.emit(scanned_count)

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

        def ignore_source_entry(source_path, rel_path, is_directory, is_link, get_stat):
            nonlocal scanned_count
            if rules.global_matches(rel_path, is_directory):
                return True
            if not is_link and not rules.pair_matches(rel_path, is_directory):
                return False
            (source_dirs if is_directory else source_files).add(relative_path_key(rel_path))
            try:
                size = 0 if is_directory else get_stat().st_size
            except OSError:
                size = 0
            add_difference("IGNORED_DIR" if is_directory else "IGNORED", rel_path, source_path, size)
            scanned_count += 1
            report_progress()
            return True

        def compare_source_file(source_path, rel_path, source_stat):
            nonlocal scanned_count
            size = source_stat.st_size
            rel_key = relative_path_key(rel_path)
            source_files.add(rel_key)
            target_path = (
                target_dir
                if target_is_file
                else os.path.join(target_dir, rel_path)
            )
            status = None
            try:
                target_stat = os.lstat(target_path)
            except FileNotFoundError:
                status = "NEW"
            else:
                if is_link_stat(target_stat):
                    add_difference("IGNORED", rel_path, source_path, size)
                    scanned_count += 1
                    return
                if not stat.S_ISREG(target_stat.st_mode):
                    raise OSError(f"Target is not a regular file: {target_path}")
                snapshot = snapshots.get(rel_key)
                if not verify_contents:
                    source_changed = (
                        snapshot != (size, source_stat.st_mtime)
                        if snapshot is not None
                        else target_stat.st_mtime < source_stat.st_mtime
                    )
                    if target_stat.st_size != size or source_changed:
                        status = "MODIFIED"
                elif target_stat.st_size != size:
                    status = "MODIFIED"
                else:
                    report_progress(rel_path)
                    source_hash = self.get_file_hash(source_path, cancel_event, source_stat)
                    if source_hash is None:
                        return
                    target_hash = self.get_file_hash(target_path, cancel_event, target_stat)
                    if target_hash is None:
                        return
                    for path, initial_stat in ((source_path, source_stat), (target_path, target_stat)):
                        if file_signature(os.stat(path)) != file_signature(initial_stat):
                            raise OSError(f"File changed during verification: {path}")
                    if source_hash != target_hash:
                        status = "MODIFIED"

            if status:
                add_difference(status, rel_path, source_path, size)

            scanned_count += 1
            report_progress()

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
                            if ignore_source_entry(
                                entry.path, rel_path, is_directory, is_link,
                                lambda: entry.stat(follow_symlinks=False),
                            ):
                                continue
                            if is_directory:
                                source_dirs.add(relative_path_key(rel_path))
                                try:
                                    target_stat = os.lstat(os.path.join(target_dir, rel_path))
                                except FileNotFoundError:
                                    target_stat = None
                                if target_stat is not None and is_link_stat(target_stat):
                                    add_difference("IGNORED_DIR", rel_path, entry.path, 0)
                                    continue
                                stack.append((entry.path, rel_path))
                                continue
                            # Windows DirEntry.stat omits identity/change fields;
                            # full stat is needed only for content verification.
                            source_stat = (
                                os.stat(entry.path, follow_symlinks=False)
                                if verify_contents else entry.stat(follow_symlinks=False)
                            )

                            compare_source_file(
                                entry.path, rel_path, source_stat
                            )
                except OSError as exc:
                    raise OSError(f"Could not scan {current_path}: {exc}") from exc

        elif os.path.isfile(source_dir):
            rel_path = os.path.basename(source_dir)
            if not ignore_source_entry(source_dir, rel_path, False, False, lambda: os.stat(source_dir)):
                compare_source_file(source_dir, rel_path, os.stat(source_dir))

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
                            rel_key = relative_path_key(rel_path)
                            try:
                                is_directory = entry.is_dir(
                                    follow_symlinks=False
                                )
                                is_link = is_directory_link(entry, is_directory)
                                if is_link:
                                    is_directory = is_directory or entry.is_dir()
                            except OSError:
                                continue

                            if rules.global_matches(rel_path, is_directory):
                                protect_parents(rel_path)
                                continue
                            if is_link or rules.pair_matches(rel_path, is_directory):
                                protect_parents(rel_path)
                                if is_link or (rel_key not in source_dirs and rel_key not in source_files):
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
                                if rel_key not in source_dirs:
                                    extra_directories.append((rel_path, entry.path))
                                stack.append((entry.path, rel_path))
                                continue

                            if rel_key not in source_files:
                                target_stat = entry.stat(follow_symlinks=False)
                                size = target_stat.st_size
                                status = "READ_ONLY" if is_read_only(target_stat) else "EXTRA"
                                if status == "READ_ONLY":
                                    protect_parents(rel_path)
                                add_difference(
                                    status, rel_path, entry.path, size
                                )

                            scanned_count += 1
                            report_progress()
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
        self.progress_updated.emit(scanned_count)
