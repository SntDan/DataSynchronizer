import os
import sqlite3
import xxhash
from PySide6.QtCore import QObject, Signal

IGNORED_FILENAMES = {
    'Thumbs.db', 'thumbs.db',
    'desktop.ini', 'Desktop.ini',
    '.DS_Store',
    '$RECYCLE.BIN',
}

class SyncScanner(QObject):
    # 信号：发送扫描进度(当前扫描数, 总发现数)
    progress_updated = Signal(int, int)
    # 信号：发送差异结果批量列表
    diff_batch_found = Signal(list)
    
    def __init__(self, db_path="sync_snapshot.db"):
        super().__init__()
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # 性能：开启 WAL，写入 fsync 频率显著降低；并发读写更友好
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.DatabaseError:
                pass

            # 检查旧表结构
            cursor = conn.execute("PRAGMA table_info(file_snapshot)")
            cols = {row[1] for row in cursor.fetchall()}

            needs_rebuild = 'src_dir' not in cols or 'dst_dir' not in cols

            if needs_rebuild and cols:
                # 保留旧数据，迁移到新表
                conn.execute("ALTER TABLE file_snapshot RENAME TO file_snapshot_old")
                conn.execute('''CREATE TABLE file_snapshot (
                    path TEXT,
                    src_dir TEXT NOT NULL DEFAULT '',
                    dst_dir TEXT NOT NULL DEFAULT '',
                    size INTEGER,
                    mtime REAL,
                    file_hash TEXT,
                    PRIMARY KEY (path, src_dir, dst_dir)
                )''')
                # 旧数据迁移（src_dir/dst_dir 填空字符串）
                conn.execute('''INSERT OR IGNORE INTO file_snapshot (path, src_dir, dst_dir, size, mtime, file_hash)
                                SELECT path, '', '', size, mtime, file_hash FROM file_snapshot_old''')
                conn.execute("DROP TABLE file_snapshot_old")
            else:
                # 全新数据库，直接建表
                conn.execute('''CREATE TABLE IF NOT EXISTS file_snapshot (
                    path TEXT,
                    src_dir TEXT NOT NULL DEFAULT '',
                    dst_dir TEXT NOT NULL DEFAULT '',
                    size INTEGER,
                    mtime REAL,
                    file_hash TEXT,
                    PRIMARY KEY (path, src_dir, dst_dir)
                )''')

    def get_file_hash(self, filepath):
        x = xxhash.xxh64()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(81920):
                    x.update(chunk)
            return x.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _count_files_iter(root):
        """迭代式统计文件数，避免递归调用栈与函数开销。"""
        if not os.path.exists(root):
            return 0
        count = 0
        stack = [root]
        while stack:
            path = stack.pop()
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            else:
                                count += 1
                        except OSError:
                            continue
            except OSError:
                pass
        return count

    def scan_and_compare(self, source_dir, target_dir, use_deep_hash=False):
        # 性能：按 src/dst 过滤快照，避免加载无关数据；元组比 dict 更轻
        snapshots = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT path, size, mtime, file_hash FROM file_snapshot "
                "WHERE src_dir=? AND dst_dir=?",
                (source_dir, target_dir)
            )
            for row in cursor:
                snapshots[row[0]] = (row[1], row[2], row[3])

        # 进行一轮快速扫描以获取总文件数量（为了真实的进度条）
        total_files_to_scan = 0
        if os.path.exists(source_dir):
            total_files_to_scan += self._count_files_iter(source_dir)
        if os.path.exists(target_dir):
            total_files_to_scan += self._count_files_iter(target_dir)

        if total_files_to_scan == 0:
            total_files_to_scan = 1  # 避免除以0

        diff_results = []
        scanned_count = 0
        source_rel_paths = set()
        source_dirs = set()

        # 性能：把热路径上反复用到的属性 / 全局解析为本地变量
        sep = os.sep
        ignored = IGNORED_FILENAMES
        diff_emit = self.diff_batch_found.emit
        progress_emit = self.progress_updated.emit
        path_join = os.path.join
        path_exists = os.path.exists
        path_getsize = os.path.getsize
        os_stat = os.stat
        get_hash = self.get_file_hash

        # ===== 主扫描：源目录（迭代式，手动维护相对前缀，免掉每文件 relpath 开销） =====
        if os.path.exists(source_dir):
            # stack 元素: (绝对路径, 相对前缀)；相对前缀 "" 表示就是 source_dir 自身
            stack = [(source_dir, "")]
            while stack:
                cur_path, cur_rel = stack.pop()
                try:
                    with os.scandir(cur_path) as it:
                        for entry in it:
                            name = entry.name
                            if cur_rel:
                                entry_rel = cur_rel + sep + name
                            else:
                                entry_rel = name

                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                            except OSError:
                                continue

                            if is_dir:
                                source_dirs.add(entry_rel)
                                stack.append((entry.path, entry_rel))
                                continue

                            if name in ignored:
                                continue

                            try:
                                stat = entry.stat()
                            except OSError:
                                continue

                            st_size = stat.st_size
                            st_mtime = stat.st_mtime
                            source_rel_paths.add(entry_rel)
                            target_path = path_join(target_dir, entry_rel)

                            status = None
                            snap = snapshots.get(entry_rel)

                            if snap is None:
                                if path_exists(target_path):
                                    if path_getsize(target_path) != st_size:
                                        status = "MODIFIED"
                                else:
                                    status = "NEW"
                            else:
                                snap_size, snap_mtime, snap_hash = snap
                                if snap_size != st_size or snap_mtime < st_mtime:
                                    if use_deep_hash:
                                        if get_hash(entry.path) != snap_hash:
                                            status = "MODIFIED"
                                    else:
                                        status = "MODIFIED"
                                else:
                                    try:
                                        if os_stat(target_path).st_size != st_size:
                                            status = "MODIFIED"
                                    except OSError:
                                        status = "NEW"

                            if status:
                                diff_results.append((status, entry_rel, entry.path, st_size))
                                if len(diff_results) >= 1000:
                                    diff_emit(diff_results)
                                    diff_results = []

                            scanned_count += 1
                            if scanned_count % 500 == 0:
                                progress_emit(scanned_count, total_files_to_scan)
                except OSError:
                    continue

        # ===== 主扫描：目标目录，找 EXTRA / EXTRA_DIR =====
        if os.path.exists(target_dir):
            stack = [(target_dir, "")]
            while stack:
                cur_path, cur_rel = stack.pop()
                try:
                    with os.scandir(cur_path) as it:
                        for entry in it:
                            name = entry.name
                            if cur_rel:
                                entry_rel = cur_rel + sep + name
                            else:
                                entry_rel = name

                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                            except OSError:
                                continue

                            if is_dir:
                                if entry_rel not in source_dirs:
                                    diff_results.append(("EXTRA_DIR", entry_rel, entry.path, 0))
                                    if len(diff_results) >= 1000:
                                        diff_emit(diff_results)
                                        diff_results = []
                                # 不论是否多余，都向下扫描以呈现内部结构
                                stack.append((entry.path, entry_rel))
                                continue

                            if name in ignored:
                                continue

                            if entry_rel not in source_rel_paths:
                                try:
                                    file_size = entry.stat().st_size
                                except OSError:
                                    file_size = 0
                                diff_results.append(("EXTRA", entry_rel, entry.path, file_size))
                                if len(diff_results) >= 1000:
                                    diff_emit(diff_results)
                                    diff_results = []

                            scanned_count += 1
                            if scanned_count % 500 == 0:
                                progress_emit(scanned_count, total_files_to_scan)
                except OSError:
                    continue

        if diff_results:
            diff_emit(diff_results)
