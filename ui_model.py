from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor


COLOR_GREEN = QColor("green")
COLOR_ORANGE = QColor("orange")
COLOR_RED = QColor("red")
COLOR_GRAY = QColor("gray")
COLOR_IGNORED = QColor("#9a9a9a")


class TreeNode:
    __slots__ = (
        "name",
        "parent",
        "children",
        "children_dict",
        "status",
        "size",
        "rel_path",
        "pair_index",
        "abs_path",
        "is_directory",
        "is_extra_group",
        "is_truncated_sync",
        "is_truncated_extra",
        "is_ellipsis_sync",
        "is_ellipsis_extra",
        "ellipsis_node_sync",
        "ellipsis_node_extra",
        "_cached_visible",
    )

    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.children = []
        self.children_dict = {}
        self.status = ""
        self.size = 0
        self.rel_path = ""
        self.pair_index = None
        self.abs_path = ""
        self.is_directory = False
        self.is_extra_group = False
        self.is_truncated_sync = True
        self.is_truncated_extra = True
        self.is_ellipsis_sync = False
        self.is_ellipsis_extra = False
        self.ellipsis_node_sync = None
        self.ellipsis_node_extra = None
        self._cached_visible = None

    @property
    def visible_children(self):
        if self._cached_visible is not None:
            return self._cached_visible

        sync_folders = []
        sync_files = []
        extra_folders = []
        extra_files = []
        for child in self.children:
            if child.is_ellipsis_extra or child.is_ellipsis_sync:
                continue
            is_extra = child.is_extra_group
            is_folder = child.is_directory or bool(child.children)
            if is_folder and is_extra:
                extra_folders.append(child)
            elif is_folder:
                sync_folders.append(child)
            elif is_extra:
                extra_files.append(child)
            else:
                sync_files.append(child)

        if self.parent is None:
            self._cached_visible = (
                sync_folders + sync_files + extra_folders + extra_files
            )
            return self._cached_visible

        visible_sync_files = sync_files
        if self.is_truncated_sync and len(sync_files) > 10:
            if self.ellipsis_node_sync is None:
                self.ellipsis_node_sync = TreeNode("... Show All", self)
                self.ellipsis_node_sync.is_ellipsis_sync = True
            visible_sync_files = sync_files[:10] + [
                self.ellipsis_node_sync
            ]

        visible_extra_files = extra_files
        if self.is_truncated_extra and len(extra_files) > 10:
            if self.ellipsis_node_extra is None:
                self.ellipsis_node_extra = TreeNode("... Show All", self)
                self.ellipsis_node_extra.is_ellipsis_extra = True
            visible_extra_files = extra_files[:10] + [
                self.ellipsis_node_extra
            ]

        self._cached_visible = (
            sync_folders
            + visible_sync_files
            + extra_folders
            + visible_extra_files
        )
        return self._cached_visible

    def add_child(self, path_parts, status, size, rel_path, pair_index=None, abs_path=""):
        node = self
        last_index = len(path_parts) - 1
        for index, part in enumerate(path_parts):
            child = node.children_dict.get(part)
            if child is None:
                child = TreeNode(part, node)
                node.children.append(child)
                node.children_dict[part] = child
                node._cached_visible = None
            if index == last_index:
                child.status = status
                child.size = size
                child.rel_path = rel_path
                child.abs_path = abs_path
                child.is_extra_group = status in ("EXTRA", "EXTRA_DIR")
            elif index > 0 or pair_index is None:
                child.rel_path = "/".join(path_parts[1:index + 1] if pair_index is not None else path_parts[:index + 1])
            child.pair_index = pair_index
            child.is_directory = index < last_index or status in ("EXTRA_DIR", "IGNORED_DIR", "PRESERVED_DIR")
            node._cached_visible = None
            node = child

    def row(self):
        if not self.parent:
            return 0
        try:
            return self.parent.visible_children.index(self)
        except ValueError:
            return 0


class DiffTreeModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rootItem = TreeNode("Root")
        self.is_mirror_mode = False

    def set_is_mirror_mode(self, is_mirror):
        if self.is_mirror_mode != is_mirror:
            self.is_mirror_mode = is_mirror
            self.layoutChanged.emit()

    def add_batch(self, diffs):
        self.beginResetModel()
        add_child = self.rootItem.add_child
        for item in diffs:
            status, rel_path, abs_path, size = item[:4]
            pair_index = None
            if len(item) >= 7:
                source_dir, target_dir, pair_index = item[4:7]
                pair_name = (
                    f"[{pair_index + 1}] {source_dir} -> {target_dir}"
                )
                parts = [pair_name]
            else:
                parts = []
            parts.extend(rel_path.replace("\\", "/").split("/"))
            add_child(parts, status, size, rel_path, pair_index, abs_path)
        self.endResetModel()

    def update_differences(self, diffs):
        """Update scan-result metadata without moving rows or replacing nodes."""
        retained = set()
        for item in diffs:
            pair_index = item[6] if len(item) >= 7 else None
            parts = item[1].replace("\\", "/").split("/")
            retained.update((pair_index, "/".join(parts[:end])) for end in range(len(parts) + 1))

        def prune(parent):
            for child in list(parent.children):
                if (child.pair_index, child.rel_path) not in retained:
                    self._remove_node(child)
                else:
                    prune(child)

        prune(self.rootItem)
        changed_parents = set()
        for item in diffs:
            status, rel_path, abs_path, size = item[:4]
            parts = rel_path.replace("\\", "/").split("/")
            if len(item) >= 7:
                source_dir, target_dir, pair_index = item[4:7]
                parts.insert(0, f"[{pair_index + 1}] {source_dir} -> {target_dir}")
            node = self.rootItem
            for part in parts:
                node = node.children_dict.get(part)
                if node is None:
                    break
            if node is None:
                continue
            if (node.status, node.size, node.abs_path) != (status, size, abs_path):
                node.status, node.size, node.abs_path = status, size, abs_path
                changed_parents.add(node.parent)

        # Keep the original grouping even when an EXTRA item becomes IGNORED.
        # No reset/layout signal: selection, expansion, and pagination survive.
        for parent in changed_parents:
            children = parent.visible_children
            if children:
                first = self.createIndex(0, 0, children[0])
                last = self.createIndex(len(children) - 1, 0, children[-1])
                self.dataChanged.emit(first, last, [Qt.DisplayRole, Qt.ForegroundRole])

    def _remove_node(self, node):
        """Remove a hidden result while preserving indexes for remaining rows."""
        parent = node.parent
        current = list(parent.visible_children)
        parent.children.remove(node)
        del parent.children_dict[node.name]
        parent._cached_visible = None
        desired = list(parent.visible_children)
        parent._cached_visible = current
        parent_index = QModelIndex() if parent is self.rootItem else self.createIndex(parent.row(), 0, parent)
        for row in range(len(current) - 1, -1, -1):
            if current[row] not in desired:
                self.beginRemoveRows(parent_index, row, row)
                current.pop(row)
                self.endRemoveRows()
        for row, child in enumerate(desired):
            if child not in current:
                self.beginInsertRows(parent_index, row, row)
                current.insert(row, child)
                self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.rootItem = TreeNode("Root")
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        parent_item = (
            self.rootItem
            if not parent.isValid()
            else parent.internalPointer()
        )
        return len(parent_item.visible_children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_item = (
            self.rootItem
            if not parent.isValid()
            else parent.internalPointer()
        )
        children = parent_item.visible_children
        if row < len(children):
            return self.createIndex(row, column, children[row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        parent_item = index.internalPointer().parent
        if parent_item == self.rootItem or parent_item is None:
            return QModelIndex()
        return self.createIndex(parent_item.row(), 0, parent_item)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = index.internalPointer()
        if role == Qt.DisplayRole:
            if item.is_ellipsis_sync or item.is_ellipsis_extra:
                return item.name
            if item.status:
                if item.is_directory or item.children:
                    return f"[{item.status}] {item.name}"
                return f"[{item.status}] {item.name} ({item.size} bytes)"
            return f"[DIR] {item.name}"

        if role == Qt.ForegroundRole:
            if item.status in ("IGNORED", "IGNORED_DIR"):
                return COLOR_IGNORED
            if item.status == "PRESERVED_DIR":
                return COLOR_GRAY
            if item.is_ellipsis_sync or item.is_ellipsis_extra:
                return COLOR_GRAY
            if item.status == "NEW":
                return COLOR_GREEN
            if item.status in ("MODIFIED", "READ_ONLY"):
                return COLOR_ORANGE
            if item.status in ("EXTRA", "EXTRA_DIR"):
                return COLOR_RED if self.is_mirror_mode else COLOR_GRAY
        return None

    def expand_ellipsis(self, index):
        if not index.isValid():
            return False
        item = index.internalPointer()
        if not (item.is_ellipsis_sync or item.is_ellipsis_extra):
            return False

        parent_item = item.parent
        self.layoutAboutToBeChanged.emit()
        if item.is_ellipsis_sync:
            parent_item.is_truncated_sync = False
        else:
            parent_item.is_truncated_extra = False
        parent_item._cached_visible = None
        self.layoutChanged.emit()
        return True
