from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex
from PySide6.QtGui import QColor

class TreeNode:
    __slots__ = ('name', 'parent', 'children', 'children_dict', 'status', 'size', 
                 'rel_path', 'is_truncated_sync', 'is_truncated_extra', 'is_ellipsis_sync', 
                 'is_ellipsis_extra', 'ellipsis_node_sync', 'ellipsis_node_extra', '_cached_visible')

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

        # 所有层级统一分组：非 EXTRA 内容排前，EXTRA/EXTRA_DIR 排后
        # 注意：status="" 的 DIR 节点（内含混合子项）也归入 sync_children，排在纯 EXTRA 前面
        sync_children = []
        extra_children = []
        for c in self.children:
            if getattr(c, 'is_ellipsis_extra', False) or getattr(c, 'is_ellipsis_sync', False):
                continue
            if c.status in ("EXTRA", "EXTRA_DIR"):
                extra_children.append(c)
            else:
                sync_children.append(c)

        # 根节点不做截断，直接合并返回
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
        if not path_parts:
            return
        
        part = path_parts[0]
        node = self.children_dict.get(part)
        if node is None:
            node = TreeNode(part, self)
            self.children.append(node)
            self.children_dict[part] = node
            self._cached_visible = None
        
        if len(path_parts) == 1:
            node.status = status
            node.size = size
            node.rel_path = rel_path
        else:
            node.add_child(path_parts[1:], status, size, rel_path)

    def row(self):
        if self.parent:
            try:
                return self.parent.visible_children.index(self)
            except ValueError:
                return 0
        return 0

class DiffTreeModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rootItem = TreeNode("Root")
        self.is_mirror_mode = False

    def set_is_mirror_mode(self, is_mirror):
        if self.is_mirror_mode != is_mirror:
            self.is_mirror_mode = is_mirror
            # 触发重新绘制，以便更新颜色
            self.layoutChanged.emit()

    def add_batch(self, diffs):
        self.beginResetModel()
        for status, rel_path, abs_path, size in diffs:
            parts = rel_path.replace('\\', '/').split('/')
            self.rootItem.add_child(parts, status, size, rel_path)
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self.rootItem = TreeNode("Root")
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0: return 0
        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()
        return len(parentItem.visible_children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent): return QModelIndex()
        parentItem = self.rootItem if not parent.isValid() else parent.internalPointer()
        visible_children = parentItem.visible_children
        if row < len(visible_children):
            childItem = visible_children[row]
            return self.createIndex(row, column, childItem)
        return QModelIndex()

    def parent(self, index):
        if not index.isValid(): return QModelIndex()
        childItem = index.internalPointer()
        parentItem = childItem.parent
        if parentItem == self.rootItem or parentItem is None:
            return QModelIndex()
        return self.createIndex(parentItem.row(), 0, parentItem)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        item = index.internalPointer()
        if role == Qt.DisplayRole:
            if getattr(item, 'is_ellipsis_sync', False) or getattr(item, 'is_ellipsis_extra', False):
                return item.name
            if item.status:
                # 不对 EXTRA_DIR 的文件夹 或者 包含子文件的文件夹显示大小
                if item.status == "EXTRA_DIR" or len(item.children) > 0:
                    return f"[{item.status}] {item.name}"
                return f"[{item.status}] {item.name} ({item.size} bytes)"
            else:
                return f"[DIR] {item.name}"
        elif role == Qt.ForegroundRole:
            if getattr(item, 'is_ellipsis_sync', False) or getattr(item, 'is_ellipsis_extra', False):
                return QColor("gray")
            if item.status == "NEW": return QColor("green")
            elif item.status == "MODIFIED": return QColor("orange")
            elif item.status in ("CONFLICT", "EXTRA", "EXTRA_DIR"): 
                if self.is_mirror_mode:
                    return QColor("red")
                else:
                    return QColor("gray")
        return None

    def expand_ellipsis(self, index):
        if not index.isValid(): return False
        item = index.internalPointer()
        if getattr(item, 'is_ellipsis_sync', False) or getattr(item, 'is_ellipsis_extra', False):
            parentItem = item.parent
            self.layoutAboutToBeChanged.emit()
            if getattr(item, 'is_ellipsis_sync', False):
                parentItem.is_truncated_sync = False
            elif getattr(item, 'is_ellipsis_extra', False):
                parentItem.is_truncated_extra = False
            parentItem._cached_visible = None # Invalidate cache
            self.layoutChanged.emit()
            return True
        return False
