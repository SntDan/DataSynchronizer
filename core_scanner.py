import os
import sqlite3
import xxhash
from concurrent.futures import ThreadPoolExecutor
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

    def scan_and_compare(self, source_dir, target_dir, use_deep_hash=False):
        snapshots = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT path, size, mtime, file_hash FROM file_snapshot")
            for row in cursor:
                snapshots[row[0]] = {'size': row[1], 'mtime': row[2], 'hash': row[3]}

        # 进行一轮快速扫描以获取总文件数量（为了真实的进度条）
        total_files_to_scan = 0
        def count_files(path):
            count = 0
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False):
                            count += count_files(entry.path)
                        else:
                            count += 1
            except OSError:
                pass
            return count

        if os.path.exists(source_dir):
            total_files_to_scan += count_files(source_dir)
        if os.path.exists(target_dir):
            total_files_to_scan += count_files(target_dir)

        if total_files_to_scan == 0:
            total_files_to_scan = 1  # 避免除以0

        diff_results = []
        scanned_count = 0
        source_rel_paths = set()
        source_dirs = set()
        
        def scan_dir(path):
            nonlocal scanned_count, diff_results
            dirs_to_visit = []
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False):
                            source_dirs.add(os.path.relpath(entry.path, source_dir))    
                            dirs_to_visit.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if entry.name in IGNORED_FILENAMES:
                                continue
                            stat = entry.stat()
                            rel_path = os.path.relpath(entry.path, source_dir)
                            source_rel_paths.add(rel_path)
                            target_path = os.path.join(target_dir, rel_path)

                            status = None
                            snap = snapshots.get(rel_path)

                            if not snap:
                                if os.path.exists(target_path):
                                    if os.path.getsize(target_path) != stat.st_size:    
                                        status = "MODIFIED"
                                else:
                                    status = "NEW"
                            else:
                                if snap['size'] != stat.st_size or snap['mtime'] < stat.st_mtime:
                                    if use_deep_hash:
                                        current_hash = self.get_file_hash(entry.path)   
                                        if current_hash != snap['hash']:
                                            status = "MODIFIED"
                                    else:
                                        status = "MODIFIED"
                                else:
                                    try:
                                        target_stat = os.stat(target_path)
                                        if target_stat.st_size != stat.st_size:
                                            status = "MODIFIED"
                                    except OSError:
                                        status = "NEW"

                            if status in ["NEW", "MODIFIED", "CONFLICT"]:
                                diff_results.append((status, rel_path, entry.path, stat.st_size))
                                if len(diff_results) >= 1000:
                                    self.diff_batch_found.emit(diff_results)
                                    diff_results = []

                            scanned_count += 1
                            if scanned_count % 500 == 0:
                                self.progress_updated.emit(scanned_count, total_files_to_scan)
            except OSError:
                pass
            
            for d in dirs_to_visit:
                scan_dir(d)

        if os.path.exists(source_dir):
            scan_dir(source_dir)

        # 无论是否打开"删除多余文件"模式，都要对比并寻找多余的内容（供UI呈现）
        if os.path.exists(target_dir):
            def scan_target(path):
                nonlocal scanned_count, diff_results
                dirs_to_visit = []
                try:
                    with os.scandir(path) as it:
                        for entry in it:
                            if entry.is_dir(follow_symlinks=False):
                                rel_path = os.path.relpath(entry.path, target_dir)  
                                if rel_path not in source_dirs and rel_path != '.': 
                                    diff_results.append(("EXTRA_DIR", rel_path, entry.path, 0))
                                    if len(diff_results) >= 1000:
                                        self.diff_batch_found.emit(diff_results)    
                                        diff_results = []
                                # 无论是不是多余文件夹，都往下扫描以展现给用户它的内部结构
                                dirs_to_visit.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                if entry.name in IGNORED_FILENAMES:
                                    continue
                                rel_path = os.path.relpath(entry.path, target_dir)
                                if rel_path not in source_rel_paths:
                                    diff_results.append(("EXTRA", rel_path, entry.path, entry.stat().st_size))
                                    if len(diff_results) >= 1000:
                                        self.diff_batch_found.emit(diff_results)
                                        diff_results = []
                                
                                scanned_count += 1
                                if scanned_count % 500 == 0:
                                    self.progress_updated.emit(scanned_count, total_files_to_scan)
                except OSError:
                    pass
                
                for d in dirs_to_visit:
                    scan_target(d)

            scan_target(target_dir)

        if diff_results:
            self.diff_batch_found.emit(diff_results)
