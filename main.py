import json
import os
import sys
import threading
import time
import subprocess
from pathlib import Path
from itertools import zip_longest

from PySide6.QtCore import QEvent, QRect, QSize, QThread, QTimer, Qt, Signal, QUrl, qWarning
from PySide6.QtGui import QDesktopServices, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from copy_manager import CopyManager
from core_scanner import SyncScanner
from ui_model import DiffTreeModel
from ignore_rules import IgnoreRules, append_ignore_path, apply_ignore_rules, relative_path_key
from storage import write_text_atomic


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "sync_snapshot.db"
IGNORE_PATH = APP_DIR / ".syncignore"
DEFAULT_LANGUAGE = "en_US"
PATH_MENU_STYLE = (
    "QMenu { padding: 3px; }"
    "QMenu::item { padding: 6px 16px 6px 8px; }"
)


UI_TEXTS = {
    "zh_CN": {
        "title": "DataSynchronizer",
        "group_label": "第{}组",
        "source_placeholder": "源文件或目录",
        "target_placeholder": "目标文件或目录",
        "change_btn": "选择",
        "choose_folder": "选择文件夹",
        "choose_file": "选择文件",
        "choose_target_file": "选择或新建文件",
        "add_group_btn": "添加组",
        "remove_group_btn": "删除组",
        "mirror_chk": "删除多余文件",
        "settings_btn": "设置",
        "save_pairs": "保存组",
        "pairs_saved": "目录对已保存",
        "settings_apply": "应用",
        "settings_cancel": "取消",
        "language_label": "语言",
        "settings_error": "无法保存设置：\n{}",
        "verify_chk": "内容校验（xxHash）",
        "verify_tip": "开启：读取两端文件并比较内容。关闭：按大小、时间和快照快速扫描。",
        "scan_btn": "1. 扫描差异",
        "sync_btn": "2. 开始同步",
        "stop_btn": "停止",
        "ready": "就绪",
        "scanning": "正在扫描第 {} / {} 组",
        "stopping": "正在停止扫描……",
        "scan_stopped": "扫描已停止",
        "scan_done": "扫描完成  新增: {}，修改: {}，多余: {}，忽略: {}，只读保留: {}",
        "hash_check": "正在校验第 {} / {} 组：{}",
        "sync_read_only": "\n只读多余文件: {} 项，将保留，不删除。",
        "scan_prog": "正在扫描第 {} / {} 组，已检查 {} 个文件",
        "start_sync": "准备开始同步",
        "sync_prog": "正在同步: {} / {}",
        "sync_done": "同步完成",
        "sync_done_msg": "所有路径组均已同步完成。",
        "sync_confirm_title": "确认同步",
        "sync_confirm_msg": (
            "即将同步 {} 组路径，请确认：\n\n"
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
        "warn_empty": "请至少设置一组源路径和目标路径。",
        "warn_source": "源文件或目录不存在：\n{}",
        "warn_overlap": "第 {} 组的源路径和目标路径不能互相包含。",
        "warn_pair_overlap": "第 {} 组和第 {} 组的路径冲突，请避免目标重叠或覆盖其他组的源路径。",
        "warn_dir_to_file": "第 {} 组不能把源目录同步到单个目标文件。",
        "warn_same": "第 {} 组的源目录和目标目录不能相同。",
        "warn_same_file": "第 {} 组的目标不能指向源文件本身。",
        "scan_error": "扫描失败：\n{}",
        "done_title": "成功",
        "browse_src": "选择源目录",
        "browse_src_file": "选择源文件",
        "browse_dst": "选择目标目录",
        "browse_dst_file": "选择或新建目标文件",
        "busy_close_title": "确认关闭",
        "busy_close": "有任务正在运行，是否停止并关闭？",
        "sync_failed": "同步未完成，失败 {} 项",
        "sync_failed_msg": "{} 个项目处理失败：\n{}",
        "open_file": "打开文件",
        "open_folder": "打开文件夹",
        "open_location": "打开文件所在位置",
        "ignore_item": "仅在当前路径组忽略",
        "ignore_global": "全局忽略（不显示）",
        "ignore_error": "无法读取或保存忽略规则：\n{}",
        "open_error": "无法打开路径：\n{}",
    },
    "en_US": {
        "title": "DataSynchronizer",
        "group_label": "Group {}",
        "source_placeholder": "Source file or directory",
        "target_placeholder": "Target file or directory",
        "change_btn": "Choose",
        "choose_folder": "Select Folder",
        "choose_file": "Select File",
        "choose_target_file": "Select or Create File",
        "add_group_btn": "Add Grp",
        "remove_group_btn": "Del Grp",
        "mirror_chk": "Remove extras",
        "settings_btn": "Settings",
        "save_pairs": "Save Groups",
        "pairs_saved": "Directory pairs saved",
        "settings_apply": "Apply",
        "settings_cancel": "Cancel",
        "language_label": "Language",
        "settings_error": "Could not save settings:\n{}",
        "verify_chk": "Verify contents (xxHash)",
        "verify_tip": "On: read and compare both files. Off: scan quickly using sizes, timestamps and snapshots.",
        "scan_btn": "1. Scan",
        "sync_btn": "2. Sync",
        "stop_btn": "Stop",
        "ready": "Ready",
        "scanning": "Scanning pair {} / {}",
        "stopping": "Stopping scan…",
        "scan_stopped": "Scan stopped",
        "scan_done": "Scan complete  New: {}, Modified: {}, Extra: {}, Ignored: {}, Read-only kept: {}",
        "hash_check": "Verifying pair {} / {}: {}",
        "sync_read_only": "\nRead-only extra files: {}; preserved without deletion.",
        "scan_prog": "Scanning pair {} / {}, checked {} files",
        "start_sync": "Preparing to synchronize",
        "sync_prog": "Synchronizing: {} / {}",
        "sync_done": "Synchronization complete",
        "sync_done_msg": "All path pairs have been synchronized.",
        "sync_confirm_title": "Confirm Synchronization",
        "sync_confirm_msg": (
            "Synchronize {} path pairs?\n\n"
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
        "warn_empty": "Please specify at least one source and target path pair.",
        "warn_source": "Source file or directory does not exist:\n{}",
        "warn_overlap": "Source and target in pair {} cannot contain one another.",
        "warn_pair_overlap": "Pairs {} and {} conflict. Targets must not overlap or cover another pair's source.",
        "warn_dir_to_file": (
            "Pair {} cannot synchronize a source directory to one file."
        ),
        "warn_same": "Source and target in pair {} cannot be the same.",
        "warn_same_file": (
            "The target in pair {} cannot resolve to the source file itself."
        ),
        "scan_error": "Scan failed:\n{}",
        "done_title": "Success",
        "browse_src": "Select Source Directory",
        "browse_src_file": "Select Source File",
        "browse_dst": "Select Target Directory",
        "browse_dst_file": "Select or Create Target File",
        "busy_close_title": "Confirm Close",
        "busy_close": "A task is running. Stop and close?",
        "sync_failed": "Synchronization incomplete: {} failed",
        "sync_failed_msg": "{} items failed:\n{}",
        "open_file": "Open File",
        "open_folder": "Open Folder",
        "open_location": "Open File Location",
        "ignore_item": "Ignore in This Pair",
        "ignore_global": "Ignore Globally (Hide)",
        "ignore_error": "Could not read or save ignore rules:\n{}",
        "open_error": "Could not open path:\n{}",
    },
}


def load_config():
    default_config = {
        "directory_pairs": [],
        "copy_workers": 4,
        "default_language": DEFAULT_LANGUAGE,
        "verify_contents": False,
        "mirror_mode": False,
    }
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        if not isinstance(data, dict):
            raise ValueError("configuration must be an object")
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
                    "target_type": (
                        str(pair.get("target_type", ""))
                        if pair.get("target_type") in ("file", "directory")
                        else ""
                    ),
                }
            )

        config = {
            "directory_pairs": pairs,
            "copy_workers": max(1, int(workers)),
            "default_language": default_language,
            "verify_contents": data.get("verify_contents") is True,
            "mirror_mode": data.get("mirror_mode") is True,
        }
        return config
    except FileNotFoundError:
        try:
            _write_config(default_config)
        except OSError:
            pass
        return default_config
    except (OSError, ValueError, TypeError, OverflowError):
        return default_config


def _write_config(data):
    write_text_atomic(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def paths_overlap(left, left_is_directory, right, right_is_directory):
    left = os.path.normcase(os.path.realpath(left))
    right = os.path.normcase(os.path.realpath(right))
    try:
        common = os.path.commonpath((left, right))
    except ValueError:
        return False
    return left == right or (left_is_directory and common == left) or (right_is_directory and common == right)


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(16)
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh_CN")
        self.language_combo.addItem("English", "en_US")
        self.language_combo.setCurrentIndex(self.language_combo.findData(parent.current_lang))
        language_layout = QHBoxLayout()
        style = self.style()
        language_layout.setContentsMargins(
            style.pixelMetric(QStyle.PM_IndicatorWidth)
            + style.pixelMetric(QStyle.PM_CheckBoxLabelSpacing), 0, 0, 0
        )
        language_layout.addWidget(self.language_label)
        language_layout.addWidget(self.language_combo, 1)
        layout.addLayout(language_layout)
        self.mirror_checkbox = QCheckBox()
        self.mirror_checkbox.setStyleSheet("QCheckBox:checked { color: red; }")
        self.mirror_checkbox.setChecked(parent.mirror_mode)
        self.verify_checkbox = QCheckBox()
        self.verify_checkbox.setChecked(parent.verify_contents)
        layout.addWidget(self.mirror_checkbox)
        layout.addWidget(self.verify_checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.apply_button.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_ui_texts()

    def update_ui_texts(self):
        text = self.parent().get_text
        self.setWindowTitle(text("settings_btn"))
        self.language_label.setText(text("language_label"))
        self.mirror_checkbox.setText(text("mirror_chk"))
        self.verify_checkbox.setText(text("verify_chk"))
        self.verify_checkbox.setToolTip(text("verify_tip"))
        self.apply_button.setText(text("settings_apply"))
        self.cancel_button.setText(text("settings_cancel"))

    def save(self):
        parent = self.parent()
        try:
            parent.save_settings(
                self.verify_checkbox.isChecked(), self.mirror_checkbox.isChecked(),
                language=self.language_combo.currentData(),
            )
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(
                self, parent.get_text("warn_title"), parent.get_text("settings_error", exc),
            )
            return
        self.update_ui_texts()


class PathButtonStyle(QProxyStyle):
    def pixelMetric(self, metric, option=None, widget=None):
        if (
            metric == QStyle.PM_MenuButtonIndicator
            and isinstance(widget, QToolButton)
        ):
            return 22
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if (
            element == QStyle.PE_IndicatorArrowDown
            and isinstance(widget, QToolButton)
        ):
            adjusted = QStyleOption(option)
            center = option.rect.center()
            center.setY(center.y() - 1)
            adjusted.rect = QRect(0, 0, 12, 8)
            adjusted.rect.moveCenter(center)
            option = adjusted
        super().drawPrimitive(element, option, painter, widget)


class ElidedLabel(QLabel):
    """Keep full status text without letting it determine the window width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def sizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def elided_text(self):
        return self.fontMetrics().elidedText(
            self.text().replace("\n", " "), Qt.ElideRight, self.contentsRect().width()
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        self.style().drawItemText(
            painter, self.contentsRect(), int(self.alignment() | Qt.TextSingleLine),
            self.palette(), self.isEnabled(), self.elided_text(), QPalette.WindowText,
        )


class SyncWorker(QThread):
    pair_started = Signal(int, int)
    failed = Signal(str)

    def __init__(self, scanner, directory_pairs, verify_contents=False):
        super().__init__()
        self.scanner = scanner
        self.directory_pairs = directory_pairs
        self.verify_contents = verify_contents
        self.cancel_event = threading.Event()
        self.was_cancelled = False
        self.differences = []

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        total = len(self.directory_pairs)
        collect = self.differences.extend
        self.scanner.diff_batch_found.connect(collect, Qt.DirectConnection)
        try:
            for index, pair in enumerate(self.directory_pairs):
                source_dir, target_dir, target_is_file = pair
                if self.cancel_event.is_set():
                    self.was_cancelled = True
                    return
                self.pair_started.emit(index + 1, total)
                self.scanner.scan_and_compare(
                    source_dir,
                    target_dir,
                    pair_index=index,
                    cancel_event=self.cancel_event,
                    target_is_file=target_is_file,
                    verify_contents=self.verify_contents,
                )
                if self.cancel_event.is_set():
                    self.was_cancelled = True
                    return
            self.differences = apply_ignore_rules(
                self.differences, self.scanner.ignore_rules, self.cancel_event
            )
            self.was_cancelled = self.cancel_event.is_set()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.scanner.diff_batch_found.disconnect(collect)


class SyncPreparationWorker(QThread):
    """Reloaded rules are applied before confirmation without blocking the UI."""

    def __init__(self, differences, rules):
        super().__init__()
        self.differences = differences
        self.rules = rules
        self.cancel_event = threading.Event()
        self.error = None

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            self.differences = apply_ignore_rules(self.differences, self.rules, self.cancel_event)
        except Exception as exc:
            self.error = str(exc)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._frame_dpr = self.devicePixelRatioF()
        self.config = load_config()
        self.verify_contents = self.config.get("verify_contents", False)
        self.mirror_mode = self.config.get("mirror_mode", False)
        self.current_lang = self.config.get(
            "default_language", DEFAULT_LANGUAGE
        )
        self.resize(880, 600)
        self.diff_data_full = []
        self.directory_pairs = []
        self.current_scan_pair = 1
        self.total_scan_pairs = 1
        self.scan_error = None
        self.status_key = "ready"
        self.status_args = ()
        self._closing = False
        self._close_prompt_open = False
        self._scan_consumed = False

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
            "QPushButton, QToolButton { font-size: 10pt; }"
        )
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.path_rows = []
        self.path_button_style = PathButtonStyle()
        self.add_group_btn = QPushButton()
        self.add_group_btn.setFixedSize(96, 30)
        self.add_group_btn.clicked.connect(
            lambda: self.add_directory_group()
        )
        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(91, 30)
        self.settings_btn.clicked.connect(self.show_settings)
        self.brand_label = QLabel(" DataSynchronizer")
        self.brand_label.setStyleSheet(
            "QLabel { font-size: 15pt; font-weight: 700; }"
        )
        top_toolbar = QHBoxLayout()
        top_toolbar.setContentsMargins(0, 0, 9, 0)
        top_toolbar.setSpacing(4)
        top_toolbar.addWidget(self.brand_label)
        top_toolbar.addStretch()
        top_toolbar.addWidget(self.settings_btn)
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
        self.list_model.set_is_mirror_mode(self.mirror_mode)
        self.list_view.setModel(self.list_model)
        self.list_view.clicked.connect(self.on_node_clicked)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_file_context_menu)

        self.save_pairs_btn = QPushButton()
        self.save_pairs_btn.setFixedSize(96, 30)
        self.save_pairs_btn.clicked.connect(self.save_directory_pairs)

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
        self.stop_btn = QPushButton()
        self.stop_btn.setFixedSize(69, 30)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setVisible(False)
        action_layout.addWidget(self.scan_btn)
        action_layout.addWidget(self.sync_btn)

        right_action_layout = QHBoxLayout()
        right_action_layout.setSpacing(26)
        right_action_layout.addWidget(self.stop_btn)
        right_action_layout.addWidget(self.save_pairs_btn)

        operation_layout = QGridLayout()
        operation_layout.setContentsMargins(3, 0, 9, 0)
        operation_layout.setHorizontalSpacing(8)
        operation_layout.addLayout(action_layout, 0, 1, Qt.AlignCenter)
        operation_layout.addLayout(
            right_action_layout, 0, 2, Qt.AlignRight | Qt.AlignVCenter
        )
        operation_layout.setColumnMinimumWidth(0, 180)
        operation_layout.setColumnMinimumWidth(2, 180)
        operation_layout.setColumnStretch(0, 1)
        operation_layout.setColumnStretch(2, 1)

        self.status_label = ElidedLabel()
        self.status_label.setStyleSheet(
            "QLabel { font-size: 10pt; font-weight: normal; }"
        )
        self.speed_label = QLabel()
        self.speed_label.hide()
        self.speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.speed_label.setMinimumWidth(80)
        self.speed_label.setStyleSheet("QLabel { font-size: 9pt; }")
        self.speed_timer = QTimer(self)
        self.speed_timer.setInterval(500)
        self.speed_timer.timeout.connect(self._update_copy_speed)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedSize(260, 10)
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.speed_label)
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
        self,
        source="",
        target="",
        adjust_window=True,
        target_type="",
    ):
        if hasattr(self, "copy_mgr") and (self._task_running() or self._closing):
            return
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
        source_input.setCursorPosition(len(source))
        source_change = QToolButton()
        source_change.setStyle(self.path_button_style)
        source_change.setToolButtonStyle(Qt.ToolButtonTextOnly)
        source_change.setPopupMode(QToolButton.MenuButtonPopup)
        source_change.setFixedSize(91, 28)
        source_menu = QMenu(source_change)
        source_menu.setStyleSheet(PATH_MENU_STYLE)
        source_folder_action = source_menu.addAction("")
        source_file_action = source_menu.addAction("")
        source_change.setMenu(source_menu)
        direction_label = QLabel("→")
        direction_label.setAlignment(Qt.AlignCenter)
        direction_label.setFixedWidth(24)
        direction_label.setStyleSheet(
            "QLabel { font-size: 14pt; font-weight: 600; }"
        )
        target_input = QLineEdit(target)
        target_input.setMinimumWidth(100)
        target_input.setCursorPosition(len(target))
        target_input.setProperty(
            "path_type",
            target_type
            if target_type in ("file", "directory")
            else ("file" if os.path.isfile(target) else "directory"),
        )
        target_change = QToolButton()
        target_change.setStyle(self.path_button_style)
        target_change.setToolButtonStyle(Qt.ToolButtonTextOnly)
        target_change.setPopupMode(QToolButton.MenuButtonPopup)
        target_change.setFixedSize(91, 28)
        target_menu = QMenu(target_change)
        target_menu.setStyleSheet(PATH_MENU_STYLE)
        target_folder_action = target_menu.addAction("")
        target_file_action = target_menu.addAction("")
        target_change.setMenu(target_menu)
        source_change.clicked.connect(source_change.showMenu)
        target_change.clicked.connect(target_change.showMenu)
        remove_button = QPushButton()
        remove_button.setFixedSize(96, 28)

        source_input.editingFinished.connect(
            lambda: self._show_path_end(source_input)
        )
        target_input.editingFinished.connect(
            lambda: self._show_path_end(target_input)
        )
        source_input.textChanged.connect(self._invalidate_scan)
        target_input.textChanged.connect(self._invalidate_scan)

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
            "source_folder_action": source_folder_action,
            "source_file_action": source_file_action,
            "target_input": target_input,
            "target_change": target_change,
            "target_folder_action": target_folder_action,
            "target_file_action": target_file_action,
            "remove_button": remove_button,
        }
        source_folder_action.triggered.connect(
            lambda: self.change_directory(source_input, "browse_src")
        )
        source_file_action.triggered.connect(
            lambda: self.change_file(source_input, "browse_src_file")
        )
        target_folder_action.triggered.connect(
            lambda: self.change_directory(
                target_input, "browse_dst", path_type="directory"
            )
        )
        target_file_action.triggered.connect(
            lambda: self.change_file(
                target_input,
                "browse_dst_file",
                save=True,
                path_type="file",
            )
        )
        remove_button.clicked.connect(
            lambda: self.remove_directory_group(row)
        )
        self.path_rows.append(row)
        self.groups_layout.addWidget(row_widget)
        self._update_group_row_texts()
        self._adjust_group_area(adjust_window)
        self._invalidate_scan()

    def remove_directory_group(self, row):
        if self._task_running() or self._closing:
            return
        if len(self.path_rows) == 1:
            row["source_input"].clear()
            row["target_input"].clear()
            row["target_input"].setProperty("path_type", "directory")
            return
        self.path_rows.remove(row)
        row["widget"].setParent(None)
        row["widget"].deleteLater()
        self._update_group_row_texts()
        self._adjust_group_area(True)
        self._invalidate_scan()

    def change_directory(self, editor, title_key, path_type=None):
        if self._task_running() or self._closing:
            return
        path = QFileDialog.getExistingDirectory(
            self, self.get_text(title_key), editor.text()
        )
        if path:
            editor.setText(path)
            if path_type:
                editor.setProperty("path_type", path_type)
            self._show_path_end(editor)
            self._invalidate_scan()

    def change_file(
        self, editor, title_key, save=False, path_type=None
    ):
        if self._task_running() or self._closing:
            return
        current_path = editor.text().strip()
        start_path = (
            current_path
            if os.path.isdir(current_path)
            else os.path.dirname(current_path)
        )
        dialog_method = (
            QFileDialog.getSaveFileName
            if save
            else QFileDialog.getOpenFileName
        )
        path, _ = dialog_method(self, self.get_text(title_key), start_path)
        if path:
            editor.setText(path)
            if path_type:
                editor.setProperty("path_type", path_type)
            self._show_path_end(editor)
            self._invalidate_scan()

    @staticmethod
    def _show_path_end(editor):
        editor.deselect()
        editor.setCursorPosition(len(editor.text()))

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
            row["source_folder_action"].setText(
                self.get_text("choose_folder")
            )
            row["source_file_action"].setText(
                self.get_text("choose_file")
            )
            row["target_change"].setText(self.get_text("change_btn"))
            row["target_folder_action"].setText(
                self.get_text("choose_folder")
            )
            row["target_file_action"].setText(
                self.get_text("choose_target_file")
            )
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
        try:
            self.scanner.ignore_rules = IgnoreRules.load(IGNORE_PATH)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, self.get_text("warn_title"), self.get_text("ignore_error", exc)
            )
        self.scanner.progress_updated.connect(self.on_scan_progress)
        self.scanner.file_check_started.connect(self.on_scan_file_check)

        self.copy_mgr = CopyManager(
            str(DB_PATH), max_workers=self.config["copy_workers"]
        )
        self.copy_mgr.overall_progress.connect(
            self.on_copy_overall_progress
        )
        self.copy_mgr.copy_finished.connect(self.on_copy_finished)

    def load_default_paths(self):
        pairs = self.config["directory_pairs"] or [
            {"source": "", "target": ""}
        ]
        for pair in pairs:
            self.add_directory_group(
                pair["source"],
                pair["target"],
                adjust_window=False,
                target_type=pair.get("target_type", ""),
            )
        self._adjust_group_area(True)

    def update_ui_texts(self):
        self.setWindowTitle(self.get_text("title"))
        self.add_group_btn.setText(self.get_text("add_group_btn"))
        self._update_group_row_texts()
        self.settings_btn.setText(self.get_text("settings_btn"))
        self.scan_btn.setText(self.get_text("scan_btn"))
        self.sync_btn.setText(self.get_text("sync_btn"))
        self.stop_btn.setText(self.get_text("stop_btn"))
        self.save_pairs_btn.setText(self.get_text("save_pairs"))
        self._render_status()

    def set_status(self, key, *args):
        self.status_key = key
        self.status_args = args
        self._render_status()

    def _render_status(self):
        self.status_label.setText(
            self.get_text(self.status_key, *self.status_args)
        )

    def show_settings(self):
        if self._task_running() or self._closing:
            return
        dialog = SettingsDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def _save_config_changes(self, **changes):
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except FileNotFoundError:
            data = dict(self.config)
        if not isinstance(data, dict):
            raise ValueError("config.json must be an object")
        data.update(changes)
        _write_config(data)
        self.config.update(data)

    def save_directory_pairs(self):
        if self._task_running() or self._closing:
            return
        try:
            self._save_config_changes(directory_pairs=[
                {
                    "source": row["source_input"].text().strip(),
                    "target": row["target_input"].text().strip(),
                    "target_type": row["target_input"].property("path_type") or "",
                }
                for row in self.path_rows
            ])
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(
                self, self.get_text("warn_title"), self.get_text("settings_error", exc)
            )
            return
        self.set_status("pairs_saved")

    def save_settings(self, verify_contents, mirror_mode, *, language=None):
        if self._task_running() or self._closing:
            return
        changes = dict(verify_contents=verify_contents, mirror_mode=mirror_mode)
        if language is not None:
            changes["default_language"] = language
        self._save_config_changes(**changes)
        if language is not None:
            self.current_lang = language
            self.update_ui_texts()
        verification_changed = self.verify_contents != verify_contents
        self.verify_contents = verify_contents
        self.mirror_mode = mirror_mode
        self.list_model.set_is_mirror_mode(mirror_mode)
        if verification_changed:
            self._invalidate_scan()
        self._update_sync_enabled()

    def _clear_scan_results(self):
        self.diff_data_full = []
        self.directory_pairs = []
        self.list_model.clear()
        self.scan_error = None
        self._scan_consumed = False
        self.sync_btn.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _invalidate_scan(self):
        if not hasattr(self, "copy_mgr") or self._task_running() or self._closing:
            return
        if self.directory_pairs or self.diff_data_full:
            self._clear_scan_results()
            self.set_status("ready")

    def _set_task_busy(self, busy, scanning=False):
        self.groups_container.setEnabled(not busy)
        self.add_group_btn.setEnabled(not busy)
        self.scan_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        self.save_pairs_btn.setEnabled(not busy)
        self.stop_btn.setVisible(busy and scanning)
        self.stop_btn.setEnabled(busy and scanning)
        if busy:
            self.sync_btn.setEnabled(False)
        else:
            self._update_sync_enabled()

    def _validated_pairs(self):
        if not self.path_rows:
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("warn_empty"),
            )
            return None

        pairs, owned_paths = [], []
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
            source_is_directory = os.path.isdir(source)
            if not source_is_directory and not os.path.isfile(source):
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_source", source),
                )
                return None
            target_is_file = row["target_input"].property("path_type") == "file"
            if os.path.isfile(target):
                target_is_file = True
            elif os.path.isdir(target):
                target_is_file = False

            if source_is_directory and target_is_file:
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text("warn_dir_to_file", index),
                )
                return None

            destination = target if source_is_directory or target_is_file else os.path.join(target, os.path.basename(source))
            if paths_overlap(source, source_is_directory, destination, source_is_directory):
                same_destination = os.path.normcase(source) == os.path.normcase(destination)
                QMessageBox.warning(
                    self,
                    self.get_text("warn_title"),
                    self.get_text(
                        ("warn_same" if source_is_directory else "warn_same_file") if same_destination else "warn_overlap",
                        index,
                    ),
                )
                return None

            for other_index, (other_source, other_destination, other_is_directory) in enumerate(owned_paths, start=1):
                if (
                    paths_overlap(destination, source_is_directory, other_destination, other_is_directory)
                    or paths_overlap(source, source_is_directory, other_destination, other_is_directory)
                    or paths_overlap(destination, source_is_directory, other_source, other_is_directory)
                ):
                    QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("warn_pair_overlap", other_index, index))
                    return None
            owned_paths.append((source, destination, source_is_directory))

            pairs.append((source, target, target_is_file))
        # Normalize editors only after all pairs have passed validation.
        for row, (source, target, target_is_file) in zip(self.path_rows, pairs):
            row["source_input"].setText(source)
            row["target_input"].setText(target)
            row["target_input"].setProperty(
                "path_type", "file" if target_is_file else "directory"
            )
            self._show_path_end(row["source_input"])
            self._show_path_end(row["target_input"])
        return pairs

    def start_scan(self):
        if self._task_running() or self._closing:
            return
        pairs = self._validated_pairs()
        if pairs is None:
            return
        try:
            self.scanner.ignore_rules = IgnoreRules.load(IGNORE_PATH)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("ignore_error", exc))
            return

        self._clear_scan_results()
        self.directory_pairs = pairs
        self.current_scan_pair = 1
        self.total_scan_pairs = len(pairs)
        self.set_status("scanning", 1, len(pairs))
        self.progress_bar.setRange(0, 0)
        self._set_task_busy(True, scanning=True)

        self.scan_worker = SyncWorker(self.scanner, pairs, self.verify_contents)
        self.scan_worker.pair_started.connect(self.on_pair_started)
        self.scan_worker.failed.connect(self.on_scan_failed)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.start()

    def stop_scan(self):
        worker = getattr(self, "scan_worker", None)
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        self.stop_btn.setEnabled(False)
        self.set_status("stopping")

    def on_pair_started(self, current, total):
        if self.scan_worker.cancel_event.is_set():
            return
        self.current_scan_pair = current
        self.total_scan_pairs = total
        self.set_status("scanning", current, total)

    def on_scan_progress(self, count):
        if self.scan_worker.cancel_event.is_set():
            return
        self.set_status(
            "scan_prog",
            self.current_scan_pair,
            self.total_scan_pairs,
            count,
        )

    def on_scan_failed(self, message):
        self.scan_error = message

    def on_scan_file_check(self, rel_path):
        if self._closing or self.scan_worker.cancel_event.is_set():
            return
        self.set_status("hash_check", self.current_scan_pair, self.total_scan_pairs, rel_path)

    def on_scan_finished(self):
        if self._closing:
            return
        self.progress_bar.setRange(0, 100)
        self._set_task_busy(False)
        if self.scan_worker.was_cancelled:
            self._clear_scan_results()
            self.set_status("scan_stopped")
            return

        self.progress_bar.setValue(100)
        if self.scan_error:
            error = self.scan_error
            self._clear_scan_results()
            self.set_status("scan_error", error)
            QMessageBox.warning(
                self,
                self.get_text("warn_title"),
                self.get_text("scan_error", error),
            )
            return

        self.diff_data_full = self.scan_worker.differences
        if self.diff_data_full:
            self.list_model.add_batch(self.diff_data_full)

        counts = self._difference_counts()
        self.set_status(
            "scan_done",
            counts["NEW"],
            counts["MODIFIED"],
            counts["EXTRA"] + counts["EXTRA_DIR"],
            counts["IGNORED"] + counts["IGNORED_DIR"],
            counts["READ_ONLY"],
        )
        self._update_sync_enabled()
        self.expand_smartly()

    def _difference_counts(self):
        counts = {
            "NEW": 0,
            "MODIFIED": 0,
            "EXTRA": 0,
            "EXTRA_DIR": 0,
            "IGNORED": 0,
            "IGNORED_DIR": 0,
            "READ_ONLY": 0,
        }
        for item in self.diff_data_full:
            status = item[0]
            if status in counts:
                counts[status] += 1
        return counts

    def _task_running(self):
        return any(
            worker is not None and worker.isRunning()
            for worker in (
                getattr(self, "scan_worker", None),
                getattr(self, "sync_preparation_worker", None),
            )
        ) or self.copy_mgr.is_syncing

    def _update_sync_enabled(self):
        statuses = {"NEW", "MODIFIED"}
        if self.mirror_mode:
            statuses.update(("EXTRA", "EXTRA_DIR"))
        self.sync_btn.setEnabled(
            not self._scan_consumed and not self._closing and not self._task_running()
            and any(item[0] in statuses for item in self.diff_data_full)
        )

    def _node_path(self, node):
        if node.abs_path:
            return node.abs_path
        if node.pair_index is None:
            return ""
        source, target, _ = self.directory_pairs[node.pair_index]
        if not node.rel_path:
            return source
        source_path = os.path.join(source, node.rel_path)
        target_path = os.path.join(target, node.rel_path)
        return source_path if os.path.exists(source_path) else target_path

    def show_file_context_menu(self, position):
        index = self.list_view.indexAt(position)
        if not index.isValid():
            return
        node = index.internalPointer()
        if node.is_ellipsis_sync or node.is_ellipsis_extra or node.pair_index is None:
            return
        self.list_view.setCurrentIndex(index)
        path = self._node_path(node)
        menu = QMenu(self)
        menu.setStyleSheet(PATH_MENU_STYLE)
        open_action = menu.addAction(self.get_text("open_folder" if os.path.isdir(path) else "open_file"))
        location_action = menu.addAction(self.get_text("open_location"))
        open_action.setEnabled(os.path.exists(path))
        location_action.setEnabled(os.path.exists(path))
        menu.addSeparator()
        ignore_action = menu.addAction(self.get_text("ignore_item"))
        ignore_action.setEnabled(bool(node.rel_path) and node.status not in ("IGNORED", "IGNORED_DIR") and not self._task_running() and not self._closing)
        global_ignore_action = menu.addAction(self.get_text("ignore_global"))
        global_ignore_action.setEnabled(bool(node.rel_path) and not self._task_running() and not self._closing)
        # Capture values before the nested menu event loop can update the model.
        rel_path, pair_index, is_directory = node.rel_path, node.pair_index, node.is_directory
        selected = menu.exec(self.list_view.viewport().mapToGlobal(position))
        menu.deleteLater()
        if selected == open_action:
            self._open_path(path)
        elif selected == location_action:
            self._open_path(path, location=True)
        elif selected == ignore_action:
            self._ignore_path(rel_path, pair_index, path, is_directory)
        elif selected == global_ignore_action:
            self._ignore_path(rel_path, pair_index, path, is_directory, global_scope=True)

    def _open_path(self, path, location=False):
        try:
            if not os.path.exists(path):
                raise OSError(path)
            if location and sys.platform == "win32":
                subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) if location else path)):
                raise OSError(path)
        except OSError:
            QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("open_error", path))

    def _ignore_path(self, rel_path, pair_index, path, is_directory, global_scope=False):
        if self._task_running() or self._closing or not 0 <= pair_index < len(self.directory_pairs):
            return
        try:
            rules = append_ignore_path(
                IGNORE_PATH, rel_path, is_directory,
                pair=None if global_scope else self.directory_pairs[pair_index],
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("ignore_error", exc))
            return
        if is_directory and not global_scope and not any(
            item[6] == pair_index
            and relative_path_key(item[1]) == relative_path_key(rel_path)
            for item in self.diff_data_full
        ):
            source, target, target_is_file = self.directory_pairs[pair_index]
            self.diff_data_full.append(("IGNORED_DIR", rel_path, path, 0, source, target, pair_index, target_is_file))
        self.diff_data_full = apply_ignore_rules(self.diff_data_full, rules)
        self._refresh_differences()

    def _refresh_differences(self):
        initial_population = not self.list_model.rootItem.children
        if initial_population:
            self.list_model.add_batch(self.diff_data_full)
        else:
            self.list_model.update_differences(self.diff_data_full)
        counts = self._difference_counts()
        self.set_status(
            "scan_done", counts["NEW"], counts["MODIFIED"],
            counts["EXTRA"] + counts["EXTRA_DIR"],
            counts["IGNORED"] + counts["IGNORED_DIR"], counts["READ_ONLY"],
        )
        self._update_sync_enabled()
        if initial_population:
            self.expand_smartly()

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
        if self._task_running() or self._closing:
            return
        try:
            rules = IgnoreRules.load(IGNORE_PATH)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("ignore_error", exc))
            return
        self._set_task_busy(True)
        self.progress_bar.setRange(0, 0)
        self.set_status("start_sync")
        self.sync_preparation_worker = SyncPreparationWorker(self.diff_data_full, rules)
        self.sync_preparation_worker.finished.connect(self.on_sync_prepared)
        self.sync_preparation_worker.start()

    def on_sync_prepared(self):
        if self._closing:
            return
        worker = self.sync_preparation_worker
        self._set_task_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        if worker.error:
            self._update_sync_enabled()
            QMessageBox.warning(self, self.get_text("warn_title"), self.get_text("ignore_error", worker.error))
            return
        self.diff_data_full = worker.differences
        self._refresh_differences()
        if not self.sync_btn.isEnabled():
            return
        counts = self._difference_counts()
        is_mirror = self.mirror_mode
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
        if counts["READ_ONLY"]:
            message += self.get_text("sync_read_only", counts["READ_ONLY"])

        reply = QMessageBox.question(
            self,
            self.get_text("sync_confirm_title"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes or self._closing:
            return

        self._set_task_busy(True)
        self.set_status("start_sync")
        self.progress_bar.setRange(0, max(len(self.diff_data_full), 1))
        self.progress_bar.setValue(0)
        self.speed_label.setText("0 B/s")
        self.speed_label.show()
        self._speed_sample = (time.monotonic(), 0)
        self.copy_mgr.start_sync(
            self.diff_data_full,
            mirror_mode=is_mirror,
            ignore_rules=worker.rules,
        )
        self.speed_timer.start()

    def _update_copy_speed(self):
        now = time.monotonic()
        copied = self.copy_mgr.bytes_copied
        previous_time, previous_bytes = self._speed_sample
        elapsed = now - previous_time
        if elapsed <= 0:
            return
        speed = max(0, copied - previous_bytes) / elapsed
        self._speed_sample = (now, copied)
        for unit in ("B/s", "KB/s", "MB/s", "GB/s", "TB/s"):
            if speed < 1024 or unit == "TB/s":
                break
            speed /= 1024
        self.speed_label.setText(f"{speed:.1f} {unit}" if unit != "B/s" else f"{speed:.0f} {unit}")

    def on_copy_overall_progress(self, current, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)
        self.set_status("sync_prog", current, total)

    def on_copy_finished(self):
        self.speed_timer.stop()
        self.speed_label.clear()
        self.speed_label.hide()
        if self._closing:
            return
        self.progress_bar.setValue(self.progress_bar.maximum())
        self._scan_consumed = True
        self._set_task_busy(False)
        if self.copy_mgr.failed_count:
            self.set_status("sync_failed", self.copy_mgr.failed_count)
            if not self._close_prompt_open:
                QMessageBox.warning(
                    self, self.get_text("warn_title"),
                    self.get_text("sync_failed_msg", self.copy_mgr.failed_count, "\n".join(self.copy_mgr.errors)),
                )
            return
        self.set_status("sync_done")
        if self._close_prompt_open:
            return
        QMessageBox.information(
            self,
            self.get_text("done_title"),
            self.get_text("sync_done_msg"),
        )

    def event(self, event):
        if (
            event.type() == QEvent.Type.DevicePixelRatioChange
            and hasattr(self, "_frame_dpr")
        ):
            self._refresh_frame_for_dpi()
        return super().event(event)

    def _refresh_frame_for_dpi(self):
        dpr = self.devicePixelRatioF()
        if dpr == self._frame_dpr:
            return
        self._frame_dpr = dpr
        if QApplication.platformName() != "windows" or self.windowHandle() is None:
            return
        # QTBUG-142163: refresh frame metrics before Qt applies DPI-scaled
        # geometry, without moving, resizing or activating the window.
        try:
            import ctypes
            from ctypes import wintypes

            set_window_pos = ctypes.WinDLL("user32", use_last_error=True).SetWindowPos
            set_window_pos.argtypes = (
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.UINT,
            )
            set_window_pos.restype = wintypes.BOOL
            # FRAMECHANGED | NOACTIVATE | NOMOVE | NOSIZE | NOZORDER | NOOWNERZORDER
            flags = 0x0020 | 0x0010 | 0x0002 | 0x0001 | 0x0004 | 0x0200
            if not set_window_pos(int(self.winId()), None, 0, 0, 0, 0, flags):
                raise ctypes.WinError(ctypes.get_last_error())
        except (AttributeError, OSError) as exc:
            qWarning(f"Could not refresh the window frame after DPI change: {exc}")

    def closeEvent(self, event):
        workers = [
            worker for worker in (
                getattr(self, "scan_worker", None),
                getattr(self, "sync_preparation_worker", None),
            )
            if worker is not None and worker.isRunning()
        ]
        if self._close_prompt_open:
            event.ignore()
            return
        if (workers or self.copy_mgr.is_syncing) and not self._closing:
            self._close_prompt_open = True
            try:
                reply = QMessageBox.question(
                    self,
                    self.get_text("busy_close_title"),
                    self.get_text("busy_close"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
            finally:
                self._close_prompt_open = False
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self._closing = True
        for worker in workers:
            worker.cancel()
        if self.copy_mgr.is_syncing:
            self.copy_mgr.cancel()

        if workers or self.copy_mgr.is_syncing:
            event.ignore()
            self.hide()
            QTimer.singleShot(50, self._close_when_workers_finish)
            return

        event.accept()

    def _close_when_workers_finish(self):
        if self._task_running():
            QTimer.singleShot(50, self._close_when_workers_finish)
            return
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    sys.exit(exit_code)
