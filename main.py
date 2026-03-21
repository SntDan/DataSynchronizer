import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QGridLayout, QPushButton, QLineEdit, QLabel, 
                               QFileDialog, QProgressBar, QTreeView, QMessageBox, QCheckBox)
from PySide6.QtCore import QThread, Qt

from ui_model import DiffTreeModel
from core_scanner import SyncScanner
from copy_manager import CopyManager

UI_TEXTS = {
    'zh_CN': {
        'title': 'DataSynchronizer',
        'src_btn': '浏览...',
        'src_label': '源目录设置:',
        'dst_btn': '浏览...',
        'dst_label': '目标目录设置:',
        'mirror_chk': '删除目标目录多余文件',
        'scan_btn': '1. 扫描差异',
        'sync_btn': '2. 开始同步',
        'lang_btn': 'English',
        'ready': '就绪。',
        'scanning': '扫描中...',
        'scan_done': '扫描完成。新增: {} 项，修改: {} 项，多余: {} 项',
        'scan_prog': '已扫描 {} 个文件...',
        'start_sync': '准备开始同步...',
        'sync_prog': '同步中: {} / {}',
        'sync_done': '同步已全部完成！',
        'sync_done_msg': '数据同步已成功完成！',
        'sync_confirm_title': '确认同步',
        'sync_confirm_msg': '即将开始同步，请确认：\n\n- 新增文件: {} 项\n- 替换文件: {} 项\n',
        'sync_confirm_mirror': '- 删除多余文件: {} 项\n- 删除多余文件夹: {} 项',
        'sync_confirm_no_mirror': '\n注: 目标有 {} 项多余文件/文件夹。由于未勾选"删除目标多余文件"，它们将不会被删除。',
        'warn_title': '警告',
        'warn_msg': '请先设置源目录和目标目录！',
        'done_title': '成功',
        'browse_src': '选择源目录',
        'browse_dst': '选择目标目录'
    },
    'en_US': {
        'title': 'DataSynchronizer',
        'src_btn': 'Browse...',
        'src_label': 'Source Dir:',
        'dst_btn': 'Browse...',
        'dst_label': 'Target Dir:',
        'mirror_chk': 'Remove Extra Files in Target',
        'scan_btn': '1. Scan Differences',
        'sync_btn': '2. Start Synchronization',
        'lang_btn': '中文',
        'ready': 'Ready.',
        'scanning': 'Scanning...',
        'scan_done': 'Scan complete. New: {}, Modified: {}, Extra: {}',
        'scan_prog': 'Scanned {} files...',
        'start_sync': 'Preparing to synchronize...',
        'sync_prog': 'Synchronizing: {} / {}',
        'sync_done': 'Synchronization complete!',
        'sync_done_msg': 'Data synchronization has been completed successfully!',
        'sync_confirm_title': 'Confirm Synchronization',
        'sync_confirm_msg': 'Are you sure you want to start the synchronization?\n\n- New files: {}\n- Modified files: {}\n',
        'sync_confirm_mirror': '- Extra files to delete: {}\n- Extra folders to delete: {}',
        'sync_confirm_no_mirror': '\nNote: {} extra items in the target will NOT be deleted because "Remove Extra Files" is unchecked.',
        'warn_title': 'Warning',
        'warn_msg': 'Please specify both source and target directories!',
        'done_title': 'Success',
        'browse_src': 'Select Source Directory',
        'browse_dst': 'Select Target Directory'
    }
}

class SyncWorker(QThread):
    def __init__(self, scanner, src, dst, deep_hash=False):
        super().__init__()
        self.scanner = scanner
        self.src = src
        self.dst = dst
        self.deep_hash = deep_hash

    def run(self):
        self.scanner.scan_and_compare(self.src, self.dst, self.deep_hash)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = 'zh_CN'
        self.resize(800, 600)
        self.diff_data_full = []
        
        self.init_ui()
        self.init_logic()
        self.update_ui_texts()

    def get_text(self, key, *args):
        text = UI_TEXTS[self.current_lang].get(key, key)
        if args:
            return text.format(*args)
        return text

    def init_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        # 目录选择区 (使用网格布局保证对齐)
        path_layout = QGridLayout()
        
        self.src_label = QLabel()
        self.src_input = QLineEdit("")
        self.src_btn = QPushButton()
        self.src_btn.clicked.connect(self.select_source)
        
        self.dst_label = QLabel()
        self.dst_input = QLineEdit("")
        self.dst_btn = QPushButton()
        self.dst_btn.clicked.connect(self.select_target)
        
        path_layout.addWidget(self.src_label, 0, 0)
        path_layout.addWidget(self.src_input, 0, 1)
        path_layout.addWidget(self.src_btn, 0, 2)
        
        path_layout.addWidget(self.dst_label, 1, 0)
        path_layout.addWidget(self.dst_input, 1, 1)
        path_layout.addWidget(self.dst_btn, 1, 2)

        # 列表区
        self.list_view = QTreeView()
        self.list_view.setHeaderHidden(True)
        self.list_model = DiffTreeModel()
        self.list_view.setModel(self.list_model)
        self.list_view.setUniformRowHeights(True)
        self.list_view.clicked.connect(self.on_node_clicked)

        # 控制选项区（多余文件打勾、语言切换等）
        control_layout = QHBoxLayout()
        self.mirror_checkbox = QCheckBox()
        self.mirror_checkbox.stateChanged.connect(self.on_mirror_checked_changed)

        self.lang_btn = QPushButton()
        self.lang_btn.clicked.connect(self.toggle_language)

        control_layout.addWidget(self.mirror_checkbox)
        control_layout.addStretch()
        control_layout.addWidget(self.lang_btn)

        # 核心操作按钮区
        action_layout = QHBoxLayout()
        btn_style = "QPushButton { font-size: 15pt; font-weight: bold; padding: 15px 40px; }"
        
        self.scan_btn = QPushButton()
        self.scan_btn.setStyleSheet(btn_style)
        self.scan_btn.clicked.connect(self.start_scan)
        
        self.sync_btn = QPushButton()
        self.sync_btn.setStyleSheet(btn_style)
        self.sync_btn.clicked.connect(self.start_sync)
        self.sync_btn.setEnabled(False)

        action_layout.addStretch()
        action_layout.addWidget(self.scan_btn)
        action_layout.addSpacing(10)
        action_layout.addWidget(self.sync_btn)
        action_layout.addStretch()

        self.status_label = QLabel()
        self.progress_bar = QProgressBar()

        layout.addLayout(path_layout)
        layout.addLayout(control_layout)
        layout.addLayout(action_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.list_view)

        self.setCentralWidget(central_widget)

    def init_logic(self):
        self.scanner = SyncScanner()
        self.scanner.progress_updated.connect(self.on_scan_progress)
        self.scanner.diff_batch_found.connect(self.on_diff_batch)

        self.copy_mgr = CopyManager()
        self.copy_mgr.overall_progress.connect(self.on_copy_overall_progress)
        self.copy_mgr.current_file_progress.connect(self.on_copy_file_progress)
        self.copy_mgr.copy_finished.connect(self.on_copy_finished)

    def update_ui_texts(self):
        self.setWindowTitle(self.get_text('title'))
        self.src_label.setText(self.get_text('src_label'))
        self.src_btn.setText(self.get_text('src_btn'))
        self.dst_label.setText(self.get_text('dst_label'))
        self.dst_btn.setText(self.get_text('dst_btn'))
        self.mirror_checkbox.setText(self.get_text('mirror_chk'))
        self.scan_btn.setText(self.get_text('scan_btn'))
        self.sync_btn.setText(self.get_text('sync_btn'))
        self.lang_btn.setText(self.get_text('lang_btn'))

        if not self.scan_btn.isEnabled() and not self.sync_btn.isEnabled():
            if hasattr(self, 'scan_worker') and self.scan_worker.isRunning():
                self.status_label.setText(self.get_text('scanning'))
            elif hasattr(self, 'copy_mgr') and getattr(self.copy_mgr, 'is_syncing', False):
                pass
            else:
                self.status_label.setText(self.get_text('start_sync'))
        else:
            if not self.diff_data_full:
                self.status_label.setText(self.get_text('ready'))
            else:
                self.status_label.setText(self.get_text('scan_done', len(self.diff_data_full)))

    def toggle_language(self):
        self.current_lang = 'en_US' if self.current_lang == 'zh_CN' else 'zh_CN'
        self.update_ui_texts()

    def select_source(self):
        path = QFileDialog.getExistingDirectory(self, self.get_text('browse_src'))
        if path: self.src_input.setText(path)

    def select_target(self):
        path = QFileDialog.getExistingDirectory(self, self.get_text('browse_dst'))
        if path: self.dst_input.setText(path)

    def start_scan(self):
        src = self.src_input.text()
        dst = self.dst_input.text()
        if not src or not dst:
            QMessageBox.warning(self, self.get_text('warn_title'), self.get_text('warn_msg'))
            return

        self.diff_data_full.clear()
        self.list_model.clear()

        self.status_label.setText(self.get_text('scanning'))
        self.progress_bar.setRange(0, 0)
        self.scan_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)

        self.scan_worker = SyncWorker(self.scanner, src, dst, deep_hash=False)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.start()

    def on_diff_batch(self, diffs):
        self.diff_data_full.extend(diffs)

    def on_scan_progress(self, count, total):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(count)
        self.status_label.setText(self.get_text('scan_prog', count))

    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        if self.diff_data_full:
            self.list_model.add_batch(self.diff_data_full)

        total_diffs = len(self.diff_data_full)
        
        new_files = sum(1 for d in self.diff_data_full if d[0] == "NEW")
        modified_files = sum(1 for d in self.diff_data_full if d[0] == "MODIFIED")
        extra_files = sum(1 for d in self.diff_data_full if d[0] in ("EXTRA", "EXTRA_DIR"))
        
        self.status_label.setText(self.get_text('scan_done', new_files, modified_files, extra_files))

        if total_diffs > 0:
            self.sync_btn.setEnabled(True)

        self.expand_smartly()

    def on_mirror_checked_changed(self, state):
        self.list_model.set_is_mirror_mode(self.mirror_checkbox.isChecked())

    def expand_smartly(self):
        # 差异项较少时全展开；中等规模展开两层（确保用户能看到文件级别内容）；
        # 超大规模时只展开顶层，避免密集渲染卡死 UI
        count = len(self.diff_data_full)
        if count < 500:
            self.list_view.expandAll()
        elif count < 5000:
            self.list_view.expandToDepth(1)
        else:
            self.list_view.expandToDepth(0)

    def on_node_clicked(self, index):
        if self.list_model.expand_ellipsis(index):
            pass

    def start_sync(self):
        new_files = sum(1 for d in self.diff_data_full if d[0] == "NEW")
        modified_files = sum(1 for d in self.diff_data_full if d[0] == "MODIFIED")
        extra_files = sum(1 for d in self.diff_data_full if d[0] == "EXTRA")
        extra_dirs = sum(1 for d in self.diff_data_full if d[0] == "EXTRA_DIR")

        is_mirror = self.mirror_checkbox.isChecked()

        msg = self.get_text('sync_confirm_msg', new_files, modified_files)
        if is_mirror:
            msg += self.get_text('sync_confirm_mirror', extra_files, extra_dirs)
        else:
            msg += self.get_text('sync_confirm_no_mirror', extra_files + extra_dirs)

        reply = QMessageBox.question(self, self.get_text('sync_confirm_title'), msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No:
            return

        self.scan_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.status_label.setText(self.get_text('start_sync'))
        self.progress_bar.setValue(0)

        self.copy_mgr.start_sync(
            self.diff_data_full,
            self.src_input.text(),
            self.dst_input.text(),
            self.mirror_checkbox.isChecked()
        )

    def on_copy_overall_progress(self, current, total):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(self.get_text('sync_prog', current, total))

    def on_copy_file_progress(self, file_path, percent):
        pass

    def on_copy_finished(self):
        self.status_label.setText(self.get_text('sync_done'))
        self.scan_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)
        QMessageBox.information(self, self.get_text('done_title'), self.get_text('sync_done_msg'))

    def closeEvent(self, event):
        import os
        os._exit(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
