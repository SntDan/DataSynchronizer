import os
import shutil
import sqlite3
import xxhash
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal

class CopyManager(QObject):
    overall_progress = Signal(int, int)
    current_file_progress = Signal(str, int)
    copy_finished = Signal()

    def __init__(self, db_path="sync_snapshot.db"):
        super().__init__()
        self.db_path = db_path
        self.max_workers = 2

    def _get_file_hash(self, filepath):
        x = xxhash.xxh64()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(81920):
                    x.update(chunk)
            return x.hexdigest()
        except OSError:
            return None

    def start_sync(self, diff_results, source_dir, target_dir, mirror_mode=False):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.mirror_mode = mirror_mode

        # 过滤掉已被某个 EXTRA_DIR 覆盖的子文件/子文件夹，避免 rmtree 后重复计数
        extra_dir_prefixes = set()
        for status, rel_path, abs_path, size in diff_results:
            if status == "EXTRA_DIR":
                norm = rel_path.replace('\\', '/')
                extra_dir_prefixes.add(norm)

        filtered = []
        for item in diff_results:
            status, rel_path, abs_path, size = item
            if status in ("EXTRA", "EXTRA_DIR"):
                norm = rel_path.replace('\\', '/')
                # 如果这条记录的路径是某个 EXTRA_DIR 的子路径，跳过
                is_child = any(
                    norm != prefix and norm.startswith(prefix + '/')
                    for prefix in extra_dir_prefixes
                )
                if is_child:
                    continue
            filtered.append(item)

        self.diff_results = filtered
        self.total_files = len(filtered)
        self.copied_count = 0

        self.diff_results.sort(key=lambda x: x[1])

        self.executor = ThreadPoolExecutor(max_workers=1)
        self.executor.submit(self._run_copy_queue)

    def _run_copy_queue(self):
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = []
            for item in self.diff_results:
                futures.append(pool.submit(self._copy_single_file, item))
            
            for f in futures:
                f.result()

        self.copy_finished.emit()

    def _copy_single_file(self, item):
        status, rel_path, source_path, size = item
        target_path = os.path.join(self.target_dir, rel_path)

        if status in ("EXTRA", "EXTRA_DIR"):
            if not self.mirror_mode:
                self.copied_count += 1
                self.overall_progress.emit(self.copied_count, self.total_files)
                return
            try:
                import stat

                def remove_readonly(func, path, exc_info):
                    try:
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    except Exception:
                        pass

                norm_rel = rel_path.replace('\\', '/')

                if status == "EXTRA_DIR":
                    if os.path.exists(target_path):
                        shutil.rmtree(target_path, onerror=remove_readonly)
                    with sqlite3.connect(self.db_path) as conn:
                        like_pattern = norm_rel + '/%'
                        conn.execute(
                            "DELETE FROM file_snapshot WHERE path LIKE ? AND src_dir=? AND dst_dir=?",
                            (like_pattern, self.source_dir, self.target_dir)
                        )
                        conn.execute(
                            "DELETE FROM file_snapshot WHERE path=? AND src_dir=? AND dst_dir=?",
                            (norm_rel, self.source_dir, self.target_dir)
                        )
                else:
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                        except OSError:
                            os.chmod(target_path, stat.S_IWRITE)
                            os.remove(target_path)
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            'DELETE FROM file_snapshot WHERE path=? AND src_dir=? AND dst_dir=?',
                            (norm_rel, self.source_dir, self.target_dir)
                        )
            except Exception as e:
                print(f"Error deleting {rel_path}: {e}")

            self.copied_count += 1
            self.overall_progress.emit(self.copied_count, self.total_files)
            return

        target_file_dir = os.path.dirname(target_path)
        os.makedirs(target_file_dir, exist_ok=True)

        chunk_size = 1024 * 1024 * 4
        copied_bytes = 0
        mode = 'wb'

        if os.path.exists(target_path):
            existing_size = os.path.getsize(target_path)
            if existing_size < size:
                copied_bytes = existing_size
                mode = 'ab'
            elif existing_size == size:
                # 目标已存在且大小一致，只更新快照
                file_hash = self._get_file_hash(source_path)
                self._update_db_snapshot(rel_path, size, os.path.getmtime(source_path), file_hash)
                self.copied_count += 1
                self.overall_progress.emit(self.copied_count, self.total_files)
                return

        try:
            with open(source_path, 'rb') as src, open(target_path, mode) as dst:
                src.seek(copied_bytes)
                while chunk := src.read(chunk_size):
                    dst.write(chunk)
                    copied_bytes += len(chunk)
                    if size > 0:
                        percent = int((copied_bytes / size) * 100)
                        self.current_file_progress.emit(rel_path, percent)

            shutil.copystat(source_path, target_path)
            # 复制完成后计算哈希并写入快照，供下次深度校验使用
            file_hash = self._get_file_hash(source_path)
            self._update_db_snapshot(rel_path, size, os.path.getmtime(source_path), file_hash)

        except Exception as e:
            print(f"Error copying {rel_path}: {e}")

        self.copied_count += 1
        self.overall_progress.emit(self.copied_count, self.total_files)

    def _update_db_snapshot(self, rel_path, size, mtime, file_hash=None):
        norm_rel = rel_path.replace('\\', '/')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO file_snapshot (path, src_dir, dst_dir, size, mtime, file_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path, src_dir, dst_dir) DO UPDATE SET
                    size=excluded.size,
                    mtime=excluded.mtime,
                    file_hash=excluded.file_hash
            ''', (norm_rel, self.source_dir, self.target_dir, size, mtime, file_hash))
