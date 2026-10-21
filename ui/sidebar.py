"""Sidebar: collections tree and request history with a shared debounced filter."""
import datetime
import json
from typing import Dict, Optional, Set

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core.models import clone_item, count_requests, new_folder, new_request
from core.urlutil import split_url
from ui import theme
from ui.request_editor import Segmented

ROLE = Qt.ItemDataRole.UserRole  # (kind, collection id, item id)
EXTRA = Qt.ItemDataRole.UserRole + 1  # method / history entry


class _TreeDelegate(QStyledItemDelegate):
    """Draws a coloured method tag before request names and a status on the right."""

    def paint(self, painter: QPainter, option, index):
        data = index.data(ROLE)
        kind = data[0] if data else ""
        if kind not in ("request", "history"):
            if kind == "collection":
                option.font.setWeight(QFont.Weight.DemiBold)
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        text = option.text
        option.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        rect = option.rect.adjusted(4, 0, -6, 0)
        method = index.data(EXTRA) if kind == "request" else index.data(EXTRA)["request"]["method"]
        small = QFont(option.font)
        small.setPointSizeF(max(6.5, option.font.pointSizeF() * 0.78))
        small.setWeight(QFont.Weight.Bold)
        painter.setFont(small)
        painter.setPen(QColor(theme.method_color(method)))
        tag_w = 46
        painter.drawText(QRect(rect.left(), rect.top(), tag_w, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         {"DELETE": "DEL", "OPTIONS": "OPT", "PATCH": "PATCH"}.get(method, method[:5]))
        right = rect.right()
        painter.setFont(option.font)
        if kind == "history":
            entry = index.data(EXTRA)
            status = entry.get("status")
            label = str(status) if status else "ERR"
            color = theme.status_color(status) if status else theme.color("danger")
            fm = painter.fontMetrics()
            sw = fm.horizontalAdvance(label)
            painter.setPen(QColor(color))
            painter.drawText(QRect(right - sw, rect.top(), sw, rect.height()), Qt.AlignmentFlag.AlignVCenter, label)
            right -= sw + 8
        painter.setPen(QColor(theme.color("text")))
        name_rect = QRect(rect.left() + tag_w, rect.top(), max(0, right - rect.left() - tag_w), rect.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, name_rect.width()))
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), 26))


class CollectionsTree(QTreeWidget):
    open_request = Signal(str, str, bool)   # collection id, request id, new tab

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._expanded: Set[str] = set()
        self._loading = False
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setAnimated(False)
        self.setUniformRowHeights(True)
        self.setItemDelegate(_TreeDelegate(self))
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(self._on_click)
        self.itemChanged.connect(self._on_renamed)
        self.itemExpanded.connect(lambda it: self._expanded.add(it.data(0, ROLE)[2] or it.data(0, ROLE)[1]))
        self.itemCollapsed.connect(lambda it: self._expanded.discard(it.data(0, ROLE)[2] or it.data(0, ROLE)[1]))
        self.refresh()

    # --- building ---------------------------------------------------------------------
    def refresh(self):
        self._loading = True
        self.clear()
        for col in self.ctx.collections.collections:
            root = QTreeWidgetItem(self, [col["name"]])
            root.setData(0, ROLE, ("collection", col["id"], ""))
            root.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                          | Qt.ItemFlag.ItemIsDropEnabled)
            root.setToolTip(0, f"{count_requests(col)} requests")
            self._add(root, col["id"], col["items"])
            root.setExpanded(col["id"] in self._expanded)
        if not self.ctx.collections.collections:
            hint = QTreeWidgetItem(self, ["No collections yet — create or import one"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setData(0, ROLE, ("hint", "", ""))
        self._loading = False

    def _add(self, parent: QTreeWidgetItem, col_id: str, items):
        for it in items:
            node = QTreeWidgetItem(parent, [it["name"]])
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable \
                | Qt.ItemFlag.ItemIsDragEnabled
            if it.get("type") == "folder":
                node.setData(0, ROLE, ("folder", col_id, it["id"]))
                node.setFlags(flags | Qt.ItemFlag.ItemIsDropEnabled)
                self._add(node, col_id, it["items"])
                node.setExpanded(it["id"] in self._expanded)
            else:
                node.setData(0, ROLE, ("request", col_id, it["id"]))
                node.setData(0, EXTRA, it["method"])
                node.setFlags(flags)
                node.setToolTip(0, f"{it['method']} {it['url']}")

    def apply_filter(self, text: str):
        text = text.lower().strip()

        def visit(item: QTreeWidgetItem) -> bool:
            data = item.data(0, ROLE)
            match = not text or text in item.text(0).lower()
            if data and data[0] == "request" and text:
                match = match or text in (item.toolTip(0) or "").lower()
            child_match = False
            for i in range(item.childCount()):
                child_match = visit(item.child(i)) or child_match
            visible = match or child_match
            item.setHidden(not visible)
            if text and child_match:
                item.setExpanded(True)
            return visible

        for i in range(self.topLevelItemCount()):
            visit(self.topLevelItem(i))
        if not text:
            self._restore_expansion()

    def _restore_expansion(self):
        def visit(item):
            data = item.data(0, ROLE)
            if data and data[0] in ("collection", "folder"):
                item.setExpanded((data[2] or data[1]) in self._expanded)
            for i in range(item.childCount()):
                visit(item.child(i))
        for i in range(self.topLevelItemCount()):
            visit(self.topLevelItem(i))

    def select_request(self, req_id: str):
        def visit(item):
            data = item.data(0, ROLE)
            if data and data[2] == req_id:
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.setCurrentItem(item)
                return True
            return any(visit(item.child(i)) for i in range(item.childCount()))
        for i in range(self.topLevelItemCount()):
            if visit(self.topLevelItem(i)):
                break

    # --- interactions -----------------------------------------------------------------
    def _on_click(self, item, _column):
        data = item.data(0, ROLE)
        if data and data[0] == "request":
            self.open_request.emit(data[1], data[2], False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            item = self.itemAt(e.position().toPoint())
            data = item.data(0, ROLE) if item else None
            if data and data[0] == "request":
                self.open_request.emit(data[1], data[2], True)
                return
        super().mouseReleaseEvent(e)

    def _target(self, data):
        col = self.ctx.collections.get(data[1])
        if col is None:
            return None, None
        if data[0] == "collection":
            return col, col
        found = self.ctx.collections.find(data[2])
        return col, found[1] if found else None

    def _menu(self, pos):
        item = self.itemAt(pos)
        menu = QMenu(self)
        if item is None or not item.data(0, ROLE) or item.data(0, ROLE)[0] == "hint":
            menu.addAction("New collection", self.new_collection)
            menu.exec(self.viewport().mapToGlobal(pos))
            menu.deleteLater()
            return
        data = item.data(0, ROLE)
        col, node = self._target(data)
        if node is None:
            menu.deleteLater()
            return
        kind = data[0]
        if kind in ("collection", "folder"):
            menu.addAction("New request", lambda: self.add_request(col, node))
            menu.addAction("New folder", lambda: self.add_folder(col, node))
            menu.addSeparator()
        if kind == "request":
            menu.addAction("Open in new tab", lambda: self.open_request.emit(col["id"], node["id"], True))
            menu.addSeparator()
        menu.addAction("Rename\tF2", lambda: self.editItem(item, 0))
        if kind in ("collection", "folder"):
            menu.addAction("Settings (auth & variables)…" if kind == "collection" else "Settings (auth)…",
                           lambda: self.edit_settings(col, node))
        menu.addAction("Duplicate", lambda: self.duplicate(col, node, kind))
        if kind == "collection":
            export = menu.addMenu("Export")
            export.addAction("Getman JSON…", lambda: self.export(col, "getman"))
            export.addAction("Postman Collection v2.1…", lambda: self.export(col, "postman"))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self.delete(col, node, kind))
        menu.exec(self.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _changed(self, col: dict):
        self.ctx.collections.save(col)
        self.ctx.collections_changed.emit()

    def new_collection(self) -> Optional[dict]:
        name, ok = QInputDialog.getText(self, "New collection", "Collection name:", text="My API")
        if ok and name.strip():
            col = self.ctx.collections.create(name.strip())
            self._expanded.add(col["id"])
            self.ctx.collections_changed.emit()
            return col
        return None

    def add_request(self, col, parent):
        req = new_request("New Request")
        parent["items"].append(req)
        self._expanded.add(parent["id"])
        self._changed(col)
        self.open_request.emit(col["id"], req["id"], True)

    def add_folder(self, col, parent):
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        if ok and name.strip():
            folder = new_folder(name.strip())
            parent["items"].append(folder)
            self._expanded.update({parent["id"], folder["id"]})
            self._changed(col)

    def duplicate(self, col, node, kind):
        if kind == "collection":
            dup = clone_item(col)
            dup["name"] = col["name"] + " copy"
            self.ctx.collections.add(dup)
            self.ctx.collections_changed.emit()
            return
        found = self.ctx.collections.find(node["id"])
        if not found:
            return
        parent = found[2][-1]
        dup = clone_item(node)
        dup["name"] = node["name"] + " copy"
        parent["items"].insert(parent["items"].index(node) + 1, dup)
        self._changed(col)

    def delete(self, col, node, kind):
        what = {"collection": "collection", "folder": "folder and everything in it", "request": "request"}[kind]
        if QMessageBox.question(self, "Delete", f"Delete {what} \"{node['name']}\"?") != \
                QMessageBox.StandardButton.Yes:
            return
        if kind == "collection":
            self.ctx.collections.delete(col["id"])
            self.ctx.collections_changed.emit()
            return
        found = self.ctx.collections.find(node["id"])
        if found:
            found[2][-1]["items"].remove(node)
            self._changed(col)

    def edit_settings(self, col, node):
        from ui.dialogs import ItemSettingsDialog
        dlg = ItemSettingsDialog(self.ctx, col, node, self)
        if dlg.exec():
            self._changed(col)
        dlg.deleteLater()

    def export(self, col, fmt):
        suffix = ".postman_collection.json" if fmt == "postman" else ".getman.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export collection", col["name"] + suffix, "JSON (*.json)")
        if not path:
            return
        if fmt == "postman":
            from core.importers.postman import export_collection
            data = export_collection(col)
        else:
            data = col
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _on_renamed(self, item, _column):
        if self._loading:
            return
        data = item.data(0, ROLE)
        if not data:
            return
        col, node = self._target(data)
        name = item.text(0).strip()
        if node is None or not name:
            return
        if node["name"] != name:
            node["name"] = name
            if data[0] == "collection":
                self.ctx.collections.collections.sort(key=lambda c: c["name"].lower())
            self._changed(col)

    def dropEvent(self, event):
        target = self.itemAt(event.position().toPoint())
        dragged = self.currentItem()
        if dragged is None or dragged.data(0, ROLE)[0] == "collection":
            event.ignore()
            return
        indicator = self.dropIndicatorPosition()
        if target is not None and target.data(0, ROLE)[0] == "request" and \
                indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()
            return
        if target is None:
            event.ignore()
            return
        super().dropEvent(event)
        self._sync_from_tree()

    def _sync_from_tree(self):
        """Rebuilds collection item order/parenting from the tree after a drag."""
        nodes: Dict[str, dict] = {}
        for col in self.ctx.collections.collections:
            stack = list(col["items"])
            while stack:
                it = stack.pop()
                nodes[it["id"]] = it
                stack.extend(it.get("items", []))

        def build(item: QTreeWidgetItem):
            out = []
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, ROLE)
                node = nodes.get(data[2])
                if node is None:
                    continue
                if node.get("type") == "folder":
                    node["items"] = build(child)
                out.append(node)
            return out

        for i in range(self.topLevelItemCount()):
            root = self.topLevelItem(i)
            data = root.data(0, ROLE)
            if not data or data[0] != "collection":
                continue
            col = self.ctx.collections.get(data[1])
            if col is None:
                continue
            col["items"] = build(root)
            self.ctx.collections.save(col)
        self.ctx.collections_changed.emit()


class HistoryTree(QTreeWidget):
    open_entry = Signal(dict, bool)
    save_entry = Signal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setHeaderHidden(True)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setItemDelegate(_TreeDelegate(self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(self._on_click)
        self._filter = ""
        self.refresh()

    def refresh(self):
        self.clear()
        today = datetime.date.today()
        group_item = None
        group_label = None
        text = self._filter
        shown = 0
        for entry in self.ctx.history.entries:
            req = entry["request"]
            if text and text not in req["url"].lower() and text not in req["method"].lower():
                continue
            day = datetime.date.fromtimestamp(entry.get("ts") or 0)
            if day == today:
                label = "Today"
            elif day == today - datetime.timedelta(days=1):
                label = "Yesterday"
            elif entry.get("ts"):
                label = day.strftime("%d %b %Y")
            else:
                label = "Older"
            if label != group_label:
                group_label = label
                group_item = QTreeWidgetItem(self, [label])
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                group_item.setData(0, ROLE, ("group", "", ""))
                group_item.setForeground(0, QColor(theme.color("text_dim")))
                group_item.setExpanded(True)
            display = split_url(req["url"])[0].split("://", 1)[-1] or req["url"]
            if split_url(req["url"])[1]:
                display += "?" + split_url(req["url"])[1]
            item = QTreeWidgetItem(group_item, [display])
            item.setData(0, ROLE, ("history", "", entry["id"]))
            item.setData(0, EXTRA, entry)
            when = datetime.datetime.fromtimestamp(entry.get("ts") or 0).strftime("%H:%M:%S")
            tip = f"{req['method']} {req['url']}\n{when}"
            if entry.get("elapsed_ms") is not None:
                tip += f" · {entry['elapsed_ms']} ms"
            if entry.get("error"):
                tip += f"\n{entry['error']}"
            item.setToolTip(0, tip)
            shown += 1
        self.expandAll()
        if not shown:
            hint = QTreeWidgetItem(self, ["No history yet" if not text else "Nothing found"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setData(0, ROLE, ("hint", "", ""))

    def apply_filter(self, text: str):
        self._filter = text.lower().strip()
        self.refresh()

    def _on_click(self, item, _col):
        data = item.data(0, ROLE)
        if data and data[0] == "history":
            self.open_entry.emit(item.data(0, EXTRA), False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            item = self.itemAt(e.position().toPoint())
            if item and item.data(0, ROLE) and item.data(0, ROLE)[0] == "history":
                self.open_entry.emit(item.data(0, EXTRA), True)
                return
        super().mouseReleaseEvent(e)

    def _menu(self, pos):
        item = self.itemAt(pos)
        menu = QMenu(self)
        if item is not None and item.data(0, ROLE) and item.data(0, ROLE)[0] == "history":
            entry = item.data(0, EXTRA)
            menu.addAction("Open", lambda: self.open_entry.emit(entry, False))
            menu.addAction("Open in new tab", lambda: self.open_entry.emit(entry, True))
            menu.addAction("Save to collection…", lambda: self.save_entry.emit(entry))
            menu.addSeparator()
            menu.addAction("Delete", lambda: self._delete(entry["id"]))
        menu.addAction("Clear all history", self._clear)
        menu.exec(self.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _delete(self, entry_id):
        self.ctx.history.remove(entry_id)
        self.ctx.history_changed.emit()

    def _clear(self):
        if QMessageBox.question(self, "Clear history", "Delete all history entries?") == \
                QMessageBox.StandardButton.Yes:
            self.ctx.history.clear()
            self.ctx.history_changed.emit()


class Sidebar(QWidget):
    import_clicked = Signal()
    new_request_clicked = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(8)
        self.switch = Segmented([("collections", "Collections"), ("history", "History")])
        self.switch.set_value("collections")
        self.switch.changed.connect(self._on_switch)
        lay.addWidget(self.switch)
        self.search = QLineEdit()
        self.search.setObjectName("SearchEdit")
        self.search.setPlaceholderText("Filter…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda: self._search_timer.start())

        self.stack = QStackedWidget()
        self.collections = CollectionsTree(ctx)
        self.history = HistoryTree(ctx)
        self.stack.addWidget(self.collections)
        self.stack.addWidget(self.history)
        lay.addWidget(self.stack, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        new_btn = QToolButton()
        new_btn.setText("+  New")
        new_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        new_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        new_menu = QMenu(new_btn)
        new_menu.addAction("Request\tCtrl+T", self.new_request_clicked.emit)
        new_menu.addAction("Collection", self.collections.new_collection)
        new_btn.setMenu(new_menu)
        bottom.addWidget(new_btn)
        bottom.addStretch()
        import_btn = QPushButton("Import")
        import_btn.setToolTip("Import Postman, Insomnia, OpenAPI, HAR, .http or cURL (Ctrl+I)")
        import_btn.clicked.connect(self.import_clicked)
        bottom.addWidget(import_btn)
        lay.addLayout(bottom)

        ctx.collections_changed.connect(self._refresh_collections)
        ctx.history_changed.connect(self.history.refresh)

    def _refresh_collections(self):
        self.collections.refresh()
        if self.search.text():
            self.collections.apply_filter(self.search.text())

    def _on_switch(self, key):
        self.stack.setCurrentIndex(0 if key == "collections" else 1)
        self._apply_filter()

    def _apply_filter(self):
        text = self.search.text()
        if self.stack.currentIndex() == 0:
            self.collections.apply_filter(text)
        else:
            self.history.apply_filter(text)

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def show_history(self):
        self.switch.set_value("history")
        self._on_switch("history")

