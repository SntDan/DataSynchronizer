import json
import os
import sys
import threading
from pathlib import Path
from itertools import zip_longest

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "sync_snapshot.db"
DEFAULT_LANGUAGE = "en_US"


UI_TEXTS = {
    "zh_CN": {
        "title": "DataSynchronizer",
        "group_label": "第{}组",
        "source_short": "源: ",
        "target_short": "目标: ",
        "source_placeholder": "源目录",
        "target_placeholder": "目标目录",
        "change_btn": "更改",
        "add_group_btn": "添加组",
        "remove_group_btn": "删除组",
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
        "done_title": "成功",
        "browse_src": "选择源目录",
        "browse_dst": "选择目标目录",
        "busy_close": "扫描或同步仍在进行，请等待任务完成后再关闭。",
    },
    "en_US": {
        "title": "DataSynchronizer",
        "group_label": "Group {}",
        "source_short": "Src:",
        "target_short": "Dst:",
        "source_placeholder": "Source directory",
        "target_placeholder": "Target directory",
        "change_btn": "Edit",
        "add_group_btn": "Add Grp",
        "remove_group_btn": "Del Grp",
        "src_btn": "Add",
        "clear_btn": "Clear",
        "src_label": "Sources:",
        "dst_btn": "Add",
        "dst_label": "Targets:",
        "mirror_chk": "Remove extras",
        "scan_btn": "1. Scan",
        "sync_btn": "2. Sync",
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
    default_config = {
        "directory_pairs": [],
        "copy_workers": 4,
        "default_language": DEFAULT_LANGUAGE,
    }
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        workers = data.get("copy_workers", 4)
        default_language = str(
            data.get("default_language", DEFAULT_LANGUAGE)
        )
        if default_language not in UI_TEXTS:
            default_language = DEFAULT_LANGUAGE
        raw_pairs = data.get("directory_pairs")
        if raw_pairs is None:
            sources = data.get("source_directories", [])
            targets = data.get("target_directories", [])
            if not isinstance(sources, list) or not isinstance(targets, list):
                raise ValueError("invalid directory configuration")
            raw_pairs = [
                {"source": source or "", "target": target or ""}
                for source, target in zip_longest(
                    sources, targets, fillvalue=""
                )
            ]
        if not isinstance(raw_pairs, list):
            raise ValueError("directory_pairs must be an array")

        pairs = []
        for pair in raw_pairs:
            if not isinstance(pair, dict):
                raise ValueError("each directory pair must be an object")
            pairs.append(
                {
                    "source": str(pair.get("source", "")),
                    "target": str(pair.get("target", "")),
                }
            )

        config = {
            "directory_pairs": pairs,
            "copy_workers": max(1, int(workers)),
            "default_language": default_language,
        }
        return config
    except FileNotFoundError:
        _write_config(default_config)
        return default_config
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default_config


def _write_config(data):
    try:
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


class SyncWorker(QThread):
    pair_started = Signal(int, int)
    failed = Signal(str)

    def __init__(self, scanner, directory_pairs, deep_hash=False):
        super().__init__()
        self.scanner = scanner
        self.directory_pairs = directory_pairs
        self.deep_hash = deep_hash
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        total = len(self.directory_pairs)
        try:
            for index, (source_dir, target_dir) in enumerate(
                self.directory_pairs
            ):
                if self.cancel_event.is_set():
                    return
                self.pair_started.emit(index + 1, total)
                self.scanner.scan_and_compare(
                    source_dir,
                    target_dir,
                    self.deep_hash,
                    pair_index=index,
                    cancel_event=self.cancel_event,
                )
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.current_lang = self.config.get(
            "default_language", DEFAULT_LANGUAGE
        )
        self.resize(880, 600)
        self.diff_data_full = []
        self.directory_pairs = []
        self.current_scan_pair = 1
        self.total_scan_pairs = 1
        self.scan_error = None
        self._closing = False

        self.init_ui()
        self.init_logic()
        self.load_default_paths()
        self.update_ui_texts()

    def get_text(self, key, *args):
        text = UI_TEXTS[self.current_lang].get(key, key)
        return text.format(*args) if args else text

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setStyleSheet(
            "QLabel, QCheckBox, QLineEdit { font-size: 10pt; }"
            "QPushButton { font-size: 10pt; }"
        )
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.path_rows = []
        self.add_group_btn = QPushButton()
        self.add_group_btn.setFixedSize(96, 30)
        self.add_group_btn.clicked.connect(
            lambda: self.add_directory_group()
        )
        self.brand_label = QLabel(" DataSynchronizer")
        self.brand_label.setStyleSheet(
            "QLabel { font-size: 15pt; font-weight: 700; }"
        )
        top_toolbar = QHBoxLayout()
        top_toolbar.setContentsMargins(0, 0, 8, 0)
        top_toolbar.setSpacing(8)
        top_toolbar.addWidget(self.brand_label)
        top_toolbar.addStretch()
        top_toolbar.addWidget(self.add_group_btn)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(6)
        self.groups_layout.setAlignment(Qt.AlignTop)
        self.groups_scroll = QScrollArea()
        self.groups_scroll.setWidgetResizable(True)
        self.groups_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.groups_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.groups_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.groups_scroll.setWidget(self.groups_container)

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
        self.lang_btn.setFixedSize(96, 30)
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

        operation_layout = QGridLayout()
        operation_layout.setContentsMargins(3, 0, 8, 0)
        operation_layout.setHorizontalSpacing(8)
        operation_layout.addWidget(
            self.mirror_checkbox, 0, 0, Qt.AlignLeft | Qt.AlignVCenter
        )
        operation_layout.addLayout(action_layout, 0, 1, Qt.AlignCenter)
        operation_layout.addWidget(
            self.lang_btn, 0, 2, Qt.AlignRight | Qt.AlignVCenter
        )
        operation_layout.setColumnMinimumWidth(0, 180)
        operation_layout.setColumnMinimumWidth(2, 180)
        operation_layout.setColumnStretch(0, 1)
        operation_layout.setColumnStretch(2, 1)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            "QLabel { font-size: 10pt; font-weight: normal; }"
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedSize(260, 10)
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(
            self.progress_bar, 0, Qt.AlignRight | Qt.AlignVCenter
        )

        layout.addLayout(top_toolbar)
        layout.addWidget(self.groups_scroll)
        layout.addLayout(operation_layout)
        layout.addWidget(self.list_view, 1)
        layout.addLayout(status_layout)
        self.setCentralWidget(central_widget)

    def add_directory_group(
        self, source="", target="", adjust_window=True
    ):
        row_widget = QFrame()
        row_widget.setObjectName("directoryGroup")
        row_widget.setStyleSheet(
            "QFrame#directoryGroup {"
            " border: 1px solid palette(mid);"
            " border-radius: 6px;"
            " background-color: palette(base);"
            "}"
        )
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(4)

        group_label = QLabel()
        group_label.setFixedWidth(52)
        source_input = QLineEdit(source)
        source_input.setMinimumWidth(100)
        source_input.setCursorPosition(0)
        source_change = QPushButton()
        source_change.setFixedSize(68, 28)
        direction_label = QLabel("→")
        direction_label.setAlignment(Qt.AlignCenter)
        direction_label.setFixedWidth(24)
        direction_label.setStyleSheet(
            "QLabel { font-size: 14pt; font-weight: 600; }"
        )
        target_input = QLineEdit(target)
        target_input.setMinimumWidth(100)
        target_input.setCursorPosition(0)
        target_change = QPushButton()
        target_change.setFixedSize(68, 28)
        remove_button = QPushButton()
        remove_button.setFixedSize(96, 28)

        source_input.editingFinished.connect(
            lambda: self._show_path_start(source_input)
        )
        target_input.editingFinished.connect(
            lambda: self._show_path_start(target_input)
        )

        row_layout.addWidget(group_label)
        row_layout.addWidget(source_input, 1)
        row_layout.addWidget(source_change)
        row_layout.addWidget(direction_label)
        row_layout.addWidget(target_input, 1)
        row_layout.addWidget(target_change)
        row_layout.addWidget(remove_button)

        row = {
            "widget": row_widget,
            "group_label": group_label,
            "source_input": source_input,
            "source_change": source_change,
            "direction_label": direction_label,
            "target_input": target_input,
            "target_change": target_change,
            "remove_button": remove_button,
        }
        source_change.clicked.connect(
            lambda: self.change_directory(source_input, "browse_src")
        )
        target_change.clicked.connect(
            lambda: self.change_directory(target_input, "browse_dst")
        )
        remove_button.clicked.connect(
            lambda: self.remove_directory_group(row)
        )
        self.path_rows.append(row)
        self.groups_layout.addWidget(row_widget)
        self._update_group_row_texts()
        self._adjust_group_area(adjust_window)

    def remove_directory_group(self, row):
        if len(self.path_rows) == 1:
            row["source_input"].clear()
            row["target_input"].clear()
            return
        self.path_rows.remove(row)
        row["widget"].setParent(None)
        row["widget"].deleteLater()
        self._update_group_row_texts()
        self._adjust_group_area(True)

    def change_directory(self, editor, title_key):
        path = QFileDialog.getExistingDirectory(
            self, self.get_text(title_key), editor.text()
        )
        if path:
            editor.setText(path)
            self._show_path_start(editor)

    @staticmethod
    def _show_path_start(editor):
        editor.deselect()
        editor.setCursorPosition(0)

    def _update_group_row_texts(self):
        for index, row in enumerate(self.path_rows, start=1):
            row["group_label"].setText(
                self.get_text("group_label", index)
            )
            row["source_input"].setPlaceholderText(
                self.get_text("source_placeholder")
            )
            row["target_input"].setPlaceholderText(
                self.get_text("target_placeholder")
            )
            row["source_change"].setText(self.get_text("change_btn"))
            row["target_change"].setText(self.get_text("change_btn"))
            row["remove_button"].setText(
                self.get_text("remove_group_btn")
            )

    def _adjust_group_area(self, resize_window=True):
        count = max(1, len(self.path_rows))
        area_height = min(50 * count, 300)
        self.groups_scroll.setFixedHeight(area_height)
        if not resize_window:
            return
        screen = QApplication.primaryScreen()
        max_height = (
            screen.availableGeometry().height() - 80 if screen else 900
        )
        desired_height = min(518 + area_height, max_height)
        self.resize(self.width(), desired_height)

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
        pairs = self.config["directory_pairs"] or [
            {"source": "", "target": ""}
        ]
        for pair in pairs:
            self.add_directory_group(
                pair["source"], pair["target"], adjust_window=False
            )
        self._adjust_group_area(True)

    def update_ui_texts(self):
        self.setWindowTitle(self.get_text("title"))
        self.add_group_btn.setText(self.get_text("add_group_btn"))
        self._update_group_row_texts()
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

    def _validated_pairs(self):
        if not self.path_rows:
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("warn_empty"),
            )
            return None

        pairs = []
        for index, row in enumerate(self.path_rows, start=1):
            source = row["source_input"].text().strip()
            target = row["target_input"].text().strip()
            if not source or not target:
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_empty"),
                )
                return None
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
            row["source_input"].setText(source)
            row["target_input"].setText(target)
            self._show_path_start(row["source_input"])
            self._show_path_start(row["target_input"])
        return pairs

    def start_scan(self):
        pairs = self._validated_pairs()
        if pairs is None:
            return

        self.directory_pairs = pairs
        self.diff_data_full.clear()
        self.list_model.clear()
        self.scan_error = None
        self.current_scan_pair = 1
        self.total_scan_pairs = len(pairs)
        self.status_label.setText(
            self.get_text("scanning", 1, len(pairs))
        )
        self.progress_bar.setRange(0, 0)
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
        if self._closing:
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
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
        self.progress_bar.setRange(0, max(len(self.diff_data_full), 1))
        self.progress_bar.setValue(0)
        self.copy_mgr.start_sync(
            self.diff_data_full,
            mirror_mode=is_mirror,
        )

    def on_copy_overall_progress(self, current, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)
        self.status_label.setText(
            self.get_text("sync_prog", current, total)
        )

    def on_copy_file_progress(self, file_path, percent):
        pass

    def on_copy_finished(self):
        if self._closing:
            return
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.status_label.setText(self.get_text("sync_done"))
        self.scan_btn.setEnabled(True)
        self.sync_btn.setEnabled(False)
        QMessageBox.information(
            self,
            self.get_text("done_title"),
            self.get_text("sync_done_msg"),
        )

    def closeEvent(self, event):
        self._closing = True
        scan_running = (
            hasattr(self, "scan_worker") and self.scan_worker.isRunning()
        )
        if scan_running:
            self.scan_worker.cancel()
            self.scan_worker.wait(3000)
        if self.copy_mgr.is_syncing:
            self.copy_mgr.cancel()
            self.copy_mgr.wait_for_finished(3.0)
        event.accept()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    os._exit(exit_code)
