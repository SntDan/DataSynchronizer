import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from copy_manager import CopyManager
from core_scanner import SyncScanner
from ui_model import DiffTreeModel


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CONFIG_PATH = APP_DIR / "sync_config.json"
DB_PATH = APP_DIR / "sync_snapshot.db"


UI_TEXTS = {
    "zh_CN": {
        "title": "DataSynchronizer",
        "src_btn": "添加",
        "clear_btn": "清空",
        "src_label": "源目录:",
        "dst_btn": "添加",
        "dst_label": "目标目录:",
        "mirror_chk": "删除多余文件",
        "scan_btn": "1. 扫描差异",
        "sync_btn": "2. 开始同步",
        "lang_btn": "English",
        "ready": "就绪",
        "scanning": "正在扫描第 {} / {} 组",
        "scan_done": "扫描完成  新增: {}，修改: {}，多余: {}",
        "scan_prog": "正在扫描第 {} / {} 组，已检查 {} 个文件",
        "start_sync": "准备开始同步",
        "sync_prog": "正在同步: {} / {}",
        "sync_done": "同步完成",
        "sync_done_msg": "所有目录组均已同步完成。",
        "sync_confirm_title": "确认同步",
        "sync_confirm_msg": (
            "即将同步 {} 组目录，请确认：\n\n"
            "- 新增文件: {}\n"
            "- 替换文件: {}\n"
        ),
        "sync_confirm_mirror": (
            "- 删除多余文件: {}\n"
            "- 删除多余文件夹: {}"
        ),
        "sync_confirm_no_mirror": (
            "\n注意：目标中 {} 个多余项目不会被删除。"
        ),
        "warn_title": "警告",
        "warn_empty": "请至少设置一组源目录和目标目录。",
        "warn_count": "源目录和目标目录数量必须一致，并按行号一一对应。",
        "warn_source": "源目录不存在或不是文件夹：\n{}",
        "warn_target": "无法创建目标目录：\n{}",
        "warn_same": "第 {} 组的源目录和目标目录不能相同。",
        "scan_error": "扫描失败：\n{}",
        "config_error": "配置文件读取失败，将使用空配置：\n{}",
        "done_title": "成功",
        "browse_src": "选择源目录",
        "browse_dst": "选择目标目录",
        "busy_close": "扫描或同步仍在进行，请等待任务完成后再关闭。",
    },
    "en_US": {
        "title": "DataSynchronizer",
        "src_btn": "Add",
        "clear_btn": "Clear",
        "src_label": "Sources:",
        "dst_btn": "Add",
        "dst_label": "Targets:",
        "mirror_chk": "Remove extras",
        "scan_btn": "1. Scan Differences",
        "sync_btn": "2. Start Synchronization",
        "lang_btn": "中文",
        "ready": "Ready",
        "scanning": "Scanning pair {} / {}",
        "scan_done": "Scan complete  New: {}, Modified: {}, Extra: {}",
        "scan_prog": "Scanning pair {} / {}, checked {} files",
        "start_sync": "Preparing to synchronize",
        "sync_prog": "Synchronizing: {} / {}",
        "sync_done": "Synchronization complete",
        "sync_done_msg": "All directory pairs have been synchronized.",
        "sync_confirm_title": "Confirm Synchronization",
        "sync_confirm_msg": (
            "Synchronize {} directory pairs?\n\n"
            "- New files: {}\n"
            "- Modified files: {}\n"
        ),
        "sync_confirm_mirror": (
            "- Extra files to delete: {}\n"
            "- Extra folders to delete: {}"
        ),
        "sync_confirm_no_mirror": (
            "\nNote: {} extra target items will not be deleted."
        ),
        "warn_title": "Warning",
        "warn_empty": "Please specify at least one source and target pair.",
        "warn_count": (
            "Source and target counts must match; lines are paired by number."
        ),
        "warn_source": "Source directory does not exist:\n{}",
        "warn_target": "Could not create target directory:\n{}",
        "warn_same": "Source and target in pair {} cannot be the same.",
        "scan_error": "Scan failed:\n{}",
        "config_error": "Could not read the config; using an empty one:\n{}",
        "done_title": "Success",
        "browse_src": "Select Source Directory",
        "browse_dst": "Select Target Directory",
        "busy_close": (
            "A scan or synchronization is still running. "
            "Please wait for it to finish."
        ),
    },
}


def load_config():
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        sources = data.get("source_directories", [])
        targets = data.get("target_directories", [])
        workers = data.get("copy_workers", 4)
        if not isinstance(sources, list) or not isinstance(targets, list):
            raise ValueError(
                "source_directories and target_directories must be arrays"
            )
        return {
            "source_directories": [str(path) for path in sources if path],
            "target_directories": [str(path) for path in targets if path],
            "copy_workers": max(1, int(workers)),
        }, None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "source_directories": [],
            "target_directories": [],
            "copy_workers": 4,
        }, str(exc)


class SyncWorker(QThread):
    pair_started = Signal(int, int)
    failed = Signal(str)

    def __init__(self, scanner, directory_pairs, deep_hash=False):
        super().__init__()
        self.scanner = scanner
        self.directory_pairs = directory_pairs
        self.deep_hash = deep_hash

    def run(self):
        total = len(self.directory_pairs)
        try:
            for index, (source_dir, target_dir) in enumerate(
                self.directory_pairs
            ):
                self.pair_started.emit(index + 1, total)
                self.scanner.scan_and_compare(
                    source_dir,
                    target_dir,
                    self.deep_hash,
                    pair_index=index,
                )
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = "zh_CN"
        self.resize(880, 600)
        self.diff_data_full = []
        self.directory_pairs = []
        self.current_scan_pair = 1
        self.total_scan_pairs = 1
        self.scan_error = None
        self.config, config_error = load_config()

        self.init_ui()
        self.init_logic()
        self.load_default_paths()
        self.update_ui_texts()

        if config_error:
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("config_error", config_error),
            )

    def get_text(self, key, *args):
        text = UI_TEXTS[self.current_lang].get(key, key)
        return text.format(*args) if args else text

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setStyleSheet(
            "QLabel, QCheckBox, QPlainTextEdit { font-size: 10pt; }"
            "QPushButton { font-size: 10pt; }"
        )
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        path_layout = QGridLayout()
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(8)

        self.src_label = QLabel()
        self.src_label.setFixedWidth(68)
        self.src_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.src_input = self._create_path_editor()
        self.src_btn = QPushButton()
        self.src_btn.clicked.connect(self.select_source)
        self.src_clear_btn = QPushButton()
        self.src_clear_btn.clicked.connect(self.src_input.clear)

        self.dst_label = QLabel()
        self.dst_label.setFixedWidth(68)
        self.dst_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.dst_input = self._create_path_editor()
        self.dst_btn = QPushButton()
        self.dst_btn.clicked.connect(self.select_target)
        self.dst_clear_btn = QPushButton()
        self.dst_clear_btn.clicked.connect(self.dst_input.clear)

        for button in (
            self.src_btn,
            self.src_clear_btn,
            self.dst_btn,
            self.dst_clear_btn,
        ):
            button.setFixedHeight(30)
        self.src_btn.setFixedWidth(82)
        self.dst_btn.setFixedWidth(82)
        self.src_clear_btn.setFixedWidth(82)
        self.dst_clear_btn.setFixedWidth(82)

        path_layout.addWidget(self.src_label, 0, 0)
        path_layout.addWidget(self.src_input, 0, 1)
        path_layout.addWidget(self.src_btn, 0, 2)
        path_layout.addWidget(self.src_clear_btn, 0, 3)
        path_layout.addWidget(self.dst_label, 1, 0)
        path_layout.addWidget(self.dst_input, 1, 1)
        path_layout.addWidget(self.dst_btn, 1, 2)
        path_layout.addWidget(self.dst_clear_btn, 1, 3)
        path_layout.setColumnStretch(1, 1)

        self.list_view = QTreeView()
        self.list_view.setHeaderHidden(True)
        self.list_view.setUniformRowHeights(True)
        self.list_view.setIndentation(18)
        self.list_model = DiffTreeModel()
        self.list_view.setModel(self.list_model)
        self.list_view.clicked.connect(self.on_node_clicked)

        self.mirror_checkbox = QCheckBox()
        self.mirror_checkbox.stateChanged.connect(
            self.on_mirror_checked_changed
        )
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedSize(82, 30)
        self.lang_btn.clicked.connect(self.toggle_language)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        button_style = (
            "QPushButton { font-size: 12pt; font-weight: 600; "
            "padding: 0 14px; }"
        )
        self.scan_btn = QPushButton()
        self.scan_btn.setStyleSheet(button_style)
        self.scan_btn.setFixedSize(200, 40)
        self.scan_btn.clicked.connect(self.start_scan)
        self.sync_btn = QPushButton()
        self.sync_btn.setStyleSheet(button_style)
        self.sync_btn.setFixedSize(200, 40)
        self.sync_btn.clicked.connect(self.start_sync)
        self.sync_btn.setEnabled(False)
        action_layout.addWidget(self.scan_btn)
        action_layout.addWidget(self.sync_btn)

        language_panel = QWidget()
        language_panel.setFixedWidth(172)
        language_layout = QHBoxLayout(language_panel)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.addStretch()
        language_layout.addWidget(self.lang_btn)

        operation_layout = QHBoxLayout()
        operation_layout.setSpacing(8)
        operation_layout.addWidget(self.mirror_checkbox)
        operation_layout.addStretch()
        operation_layout.addLayout(action_layout)
        operation_layout.addWidget(language_panel)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            "QLabel { font-size: 10pt; font-weight: normal; }"
        )

        layout.addLayout(path_layout)
        layout.addLayout(operation_layout)
        layout.addWidget(self.list_view, 1)
        layout.addWidget(self.status_label)
        self.setCentralWidget(central_widget)

    @staticmethod
    def _create_path_editor():
        editor = QPlainTextEdit()
        editor.setFixedHeight(50)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.setStyleSheet("QPlainTextEdit { padding: 3px 6px; }")
        editor.setTabChangesFocus(True)
        return editor

    def init_logic(self):
        self.scanner = SyncScanner(str(DB_PATH))
        self.scanner.progress_updated.connect(self.on_scan_progress)
        self.scanner.diff_batch_found.connect(self.on_diff_batch)

        self.copy_mgr = CopyManager(
            str(DB_PATH), max_workers=self.config["copy_workers"]
        )
        self.copy_mgr.overall_progress.connect(
            self.on_copy_overall_progress
        )
        self.copy_mgr.current_file_progress.connect(
            self.on_copy_file_progress
        )
        self.copy_mgr.copy_finished.connect(self.on_copy_finished)

    def load_default_paths(self):
        self.src_input.setPlainText(
            "\n".join(self.config["source_directories"])
        )
        self.dst_input.setPlainText(
            "\n".join(self.config["target_directories"])
        )

    def save_config(self):
        data = {
            "source_directories": self._path_lines(self.src_input),
            "target_directories": self._path_lines(self.dst_input),
            "copy_workers": self.copy_mgr.max_workers,
        }
        temp_path = CONFIG_PATH.with_suffix(".json.tmp")
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temp_path, CONFIG_PATH)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def update_ui_texts(self):
        self.setWindowTitle(self.get_text("title"))
        self.src_label.setText(self.get_text("src_label"))
        self.src_btn.setText(self.get_text("src_btn"))
        self.src_clear_btn.setText(self.get_text("clear_btn"))
        self.dst_label.setText(self.get_text("dst_label"))
        self.dst_btn.setText(self.get_text("dst_btn"))
        self.dst_clear_btn.setText(self.get_text("clear_btn"))
        self.mirror_checkbox.setText(self.get_text("mirror_chk"))
        self.scan_btn.setText(self.get_text("scan_btn"))
        self.sync_btn.setText(self.get_text("sync_btn"))
        self.lang_btn.setText(self.get_text("lang_btn"))
        if not self.diff_data_full:
            self.status_label.setText(self.get_text("ready"))

    def toggle_language(self):
        self.current_lang = (
            "en_US" if self.current_lang == "zh_CN" else "zh_CN"
        )
        self.update_ui_texts()

    @staticmethod
    def _path_lines(editor):
        return [
            line.strip()
            for line in editor.toPlainText().splitlines()
            if line.strip()
        ]

    @staticmethod
    def _append_path(editor, path):
        paths = MainWindow._path_lines(editor)
        if path not in paths:
            paths.append(path)
            editor.setPlainText("\n".join(paths))
            editor.moveCursor(QTextCursor.End)

    def select_source(self):
        path = QFileDialog.getExistingDirectory(
            self, self.get_text("browse_src")
        )
        if path:
            self._append_path(self.src_input, path)

    def select_target(self):
        path = QFileDialog.getExistingDirectory(
            self, self.get_text("browse_dst")
        )
        if path:
            self._append_path(self.dst_input, path)

    def _validated_pairs(self):
        sources = self._path_lines(self.src_input)
        targets = self._path_lines(self.dst_input)
        if not sources or not targets:
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("warn_empty"),
            )
            return None
        if len(sources) != len(targets):
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("warn_count"),
            )
            return None

        pairs = []
        for index, (source, target) in enumerate(
            zip(sources, targets), start=1
        ):
            source = os.path.normpath(
                os.path.abspath(os.path.expandvars(os.path.expanduser(source)))
            )
            target = os.path.normpath(
                os.path.abspath(os.path.expandvars(os.path.expanduser(target)))
            )
            if not os.path.isdir(source):
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_source", source),
                )
                return None
            try:
                os.makedirs(target, exist_ok=True)
            except OSError:
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_target", target),
                )
                return None
            if os.path.normcase(source) == os.path.normcase(target):
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_same", index),
                )
                return None
            pairs.append((source, target))

        self.src_input.setPlainText(
            "\n".join(source for source, _ in pairs)
        )
        self.dst_input.setPlainText(
            "\n".join(target for _, target in pairs)
        )
        return pairs

    def start_scan(self):
        pairs = self._validated_pairs()
        if pairs is None:
            return

        self.directory_pairs = pairs
        self.save_config()
        self.diff_data_full.clear()
        self.list_model.clear()
        self.scan_error = None
        self.current_scan_pair = 1
        self.total_scan_pairs = len(pairs)
        self.status_label.setText(
            self.get_text("scanning", 1, len(pairs))
        )
        self.scan_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)

        self.scan_worker = SyncWorker(self.scanner, pairs, deep_hash=False)
        self.scan_worker.pair_started.connect(self.on_pair_started)
        self.scan_worker.failed.connect(self.on_scan_failed)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.start()

    def on_pair_started(self, current, total):
        self.current_scan_pair = current
        self.total_scan_pairs = total
        self.status_label.setText(
            self.get_text("scanning", current, total)
        )

    def on_diff_batch(self, differences):
        self.diff_data_full.extend(differences)

    def on_scan_progress(self, count, total):
        self.status_label.setText(
            self.get_text(
                "scan_prog",
                self.current_scan_pair,
                self.total_scan_pairs,
                count,
            )
        )

    def on_scan_failed(self, message):
        self.scan_error = message

    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        if self.scan_error:
            self.status_label.setText(
                self.get_text("scan_error", self.scan_error)
            )
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("scan_error", self.scan_error),
            )
            return

        if self.diff_data_full:
            self.list_model.add_batch(self.diff_data_full)

        counts = self._difference_counts()
        self.status_label.setText(
            self.get_text(
                "scan_done",
                counts["NEW"],
                counts["MODIFIED"],
                counts["EXTRA"] + counts["EXTRA_DIR"],
            )
        )
        self.sync_btn.setEnabled(bool(self.diff_data_full))
        self.expand_smartly()

    def _difference_counts(self):
        counts = {
            "NEW": 0,
            "MODIFIED": 0,
            "EXTRA": 0,
            "EXTRA_DIR": 0,
        }
        for item in self.diff_data_full:
            status = item[0]
            if status in counts:
                counts[status] += 1
        return counts

    def on_mirror_checked_changed(self, state):
        self.list_model.set_is_mirror_mode(
            self.mirror_checkbox.isChecked()
        )

    def expand_smartly(self):
        count = len(self.diff_data_full)
        if count < 500:
            self.list_view.expandAll()
        elif count < 5000:
            self.list_view.expandToDepth(1)
        else:
            self.list_view.expandToDepth(0)

    def on_node_clicked(self, index):
        self.list_model.expand_ellipsis(index)

    def start_sync(self):
        counts = self._difference_counts()
        is_mirror = self.mirror_checkbox.isChecked()
        message = self.get_text(
            "sync_confirm_msg",
            len(self.directory_pairs),
            counts["NEW"],
            counts["MODIFIED"],
        )
        if is_mirror:
            message += self.get_text(
                "sync_confirm_mirror",
                counts["EXTRA"],
                counts["EXTRA_DIR"],
            )
        else:
            message += self.get_text(
                "sync_confirm_no_mirror",
                counts["EXTRA"] + counts["EXTRA_DIR"],
            )

        reply = QMessageBox.question(
            self,
            self.get_text("sync_confirm_title"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        self.scan_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.status_label.setText(self.get_text("start_sync"))
        self.copy_mgr.start_sync(
            self.diff_data_full,
            mirror_mode=is_mirror,
        )

    def on_copy_overall_progress(self, current, total):
        self.status_label.setText(
            self.get_text("sync_prog", current, total)
        )

    def on_copy_file_progress(self, file_path, percent):
        pass

    def on_copy_finished(self):
        self.status_label.setText(self.get_text("sync_done"))
        self.scan_btn.setEnabled(True)
        self.sync_btn.setEnabled(False)
        QMessageBox.information(
            self,
            self.get_text("done_title"),
            self.get_text("sync_done_msg"),
        )

    def closeEvent(self, event):
        scan_running = (
            hasattr(self, "scan_worker") and self.scan_worker.isRunning()
        )
        if scan_running or self.copy_mgr.is_syncing:
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("busy_close"),
            )
            event.ignore()
            return
        self.save_config()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
