from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor


COLOR_GREEN = QColor("green")
COLOR_ORANGE = QColor("orange")
COLOR_RED = QColor("red")
COLOR_GRAY = QColor("gray")


class TreeNode:
    __slots__ = (
        "name",
        "parent",
        "children",
        "children_dict",
        "status",
        "size",
        "rel_path",
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

        sync_children = []
        extra_children = []
        for child in self.children:
            if child.is_ellipsis_extra or child.is_ellipsis_sync:
                continue
            if child.status in ("EXTRA", "EXTRA_DIR"):
                extra_children.append(child)
            else:
                sync_children.append(child)

        if self.parent is None:
            self._cached_visible = sync_children + extra_children
            return self._cached_visible

        visible_sync = sync_children
        if self.is_truncated_sync and len(sync_children) > 10:
            if self.ellipsis_node_sync is None:
                self.ellipsis_node_sync = TreeNode("... Show All", self)
                self.ellipsis_node_sync.is_ellipsis_sync = True
            visible_sync = sync_children[:10] + [self.ellipsis_node_sync]

        visible_extra = extra_children
        if self.is_truncated_extra and len(extra_children) > 10:
            if self.ellipsis_node_extra is None:
                self.ellipsis_node_extra = TreeNode("... Show All", self)
                self.ellipsis_node_extra.is_ellipsis_extra = True
            visible_extra = extra_children[:10] + [self.ellipsis_node_extra]

        self._cached_visible = visible_sync + visible_extra
        return self._cached_visible

    def add_child(self, path_parts, status, size, rel_path):
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
            status, rel_path, _, size = item[:4]
            if len(item) >= 7:
                source_dir, target_dir, pair_index = item[4:7]
                pair_name = (
                    f"[{pair_index + 1}] {source_dir} -> {target_dir}"
                )
                parts = [pair_name]
            else:
                parts = []
            parts.extend(rel_path.replace("\\", "/").split("/"))
            add_child(parts, status, size, rel_path)
        self.endResetModel()

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
                if item.status == "EXTRA_DIR" or item.children:
                    return f"[{item.status}] {item.name}"
                return f"[{item.status}] {item.name} ({item.size} bytes)"
            return f"[DIR] {item.name}"

        if role == Qt.ForegroundRole:
            if item.is_ellipsis_sync or item.is_ellipsis_extra:
                return COLOR_GRAY
            if item.status == "NEW":
                return COLOR_GREEN
            if item.status == "MODIFIED":
                return COLOR_ORANGE
            if item.status in ("EXTRA", "EXTRA_DIR", "CONFLICT"):
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
