"""Dialogs: environments, settings, collection/folder settings, save request,
keyboard shortcuts."""
import json
import os
import zipfile
from datetime import datetime
from typing import Optional, Tuple

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core.paths import data_dir
from ui.auth_editor import AuthEditor
from ui.kv_table import KeyValueTable


def plain_buttons(box: QDialogButtonBox) -> QDialogButtonBox:
    """Drops the platform's stock icons from dialog buttons."""
    for button in box.buttons():
        button.setIcon(QIcon())
    return box


def _buttons(dialog: QDialog, ok_text: str = "Save") -> QDialogButtonBox:
    box = plain_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel))
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setObjectName("Primary")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class ItemSettingsDialog(QDialog):
    """Collection: name, auth, variables, description. Folder: name, auth."""

    def __init__(self, ctx, collection: dict, node: dict, parent=None):
        super().__init__(parent)
        self.collection, self.node = collection, node
        is_col = node is collection
        self.setWindowTitle("Collection settings" if is_col else "Folder settings")
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(node["name"])
        form.addRow("Name", self.name)
        lay.addLayout(form)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        variables = lambda: ctx.var_context(collection).names()  # noqa: E731
        self.auth = AuthEditor(allow_inherit=not is_col, variables=variables)
        self.auth.set_auth(node.get("auth"))
        self.auth.set_inherit_hint("Uses the auth of the parent folder or collection.")
        self.vars = None
        self.desc = None
        if is_col:
            self.vars = KeyValueTable(placeholders=("Variable", "Value"), variables=variables)
            self.vars.set_rows(collection.get("variables", []))
            vars_page = QWidget()
            vl = QVBoxLayout(vars_page)
            vl.setContentsMargins(0, 8, 0, 0)
            hint = QLabel("Collection variables are available to every request in this collection. "
                          "The active environment overrides them.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            vl.addWidget(hint)
            vl.addWidget(self.vars)
            tabs.addTab(vars_page, "Variables")
        tabs.addTab(self.auth, "Auth")
        if is_col:
            self.desc = QPlainTextEdit(collection.get("description", ""))
            tabs.addTab(self.desc, "Description")
        lay.addWidget(tabs, 1)
        lay.addWidget(_buttons(self))

    def accept(self):
        name = self.name.text().strip()
        if name:
            self.node["name"] = name
        self.node["auth"] = self.auth.auth()
        if self.vars is not None:
            self.collection["variables"] = [r for r in self.vars.rows() if r["key"]]
        if self.desc is not None:
            self.collection["description"] = self.desc.toPlainText()
        super().accept()


class EnvironmentDialog(QDialog):
    GLOBALS = "__globals__"

    def __init__(self, ctx, parent=None, select_id: Optional[str] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Environments")
        self.resize(860, 540)
        self._current: Optional[str] = None
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(lambda _it: self._rename())
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in (("Add", self._add), ("Duplicate", self._duplicate), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        ll.addLayout(row)
        row2 = QHBoxLayout()
        imp, exp = QPushButton("Import…"), QPushButton("Export…")
        imp.setToolTip("Import a Postman environment file")
        imp.clicked.connect(self._import)
        exp.clicked.connect(self._export)
        row2.addWidget(imp)
        row2.addWidget(exp)
        ll.addLayout(row2)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("Title")
        head.addWidget(self.title)
        head.addStretch()
        self.active_btn = QPushButton("Set active")
        self.active_btn.clicked.connect(self._set_active)
        head.addWidget(self.active_btn)
        rl.addLayout(head)
        self.hint = QLabel()
        self.hint.setObjectName("Dim")
        self.hint.setWordWrap(True)
        rl.addWidget(self.hint)
        self.table = KeyValueTable(placeholders=("Variable", "Value"),
                                   variables=lambda: ctx.var_context().names())
        self.table.changed.connect(self._store_rows)
        rl.addWidget(self.table, 1)
        split.addWidget(right)
        split.setSizes([240, 620])
        lay.addWidget(split, 1)
        box = plain_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.StandardButton.Close).setText("Done")
        lay.addWidget(box)
        self._fill(select_id or ctx.envs.active_id or self.GLOBALS)

    def _fill(self, select: Optional[str] = None):
        self.list.blockSignals(True)
        self.list.clear()
        g = QListWidgetItem("Globals")
        g.setData(Qt.ItemDataRole.UserRole, self.GLOBALS)
        self.list.addItem(g)
        for env in self.ctx.envs.environments:
            mark = "  ●" if env["id"] == self.ctx.envs.active_id else ""
            it = QListWidgetItem(env["name"] + mark)
            it.setData(Qt.ItemDataRole.UserRole, env["id"])
            self.list.addItem(it)
        self.list.blockSignals(False)
        target = 0
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == select:
                target = i
        self._current = None
        self.list.setCurrentRow(target)
        self._on_select(self.list.currentItem(), None)

    def _rows_target(self):
        if self._current == self.GLOBALS:
            return None
        return self.ctx.envs.get(self._current)

    def _on_select(self, item, _prev):
        if item is None:
            return
        self._current = item.data(Qt.ItemDataRole.UserRole)
        env = self._rows_target()
        if env is None:
            self.title.setText("Globals")
            self.hint.setText("Global variables are available everywhere; any environment overrides them.")
            self.table.set_rows(self.ctx.envs.globals)
            self.active_btn.hide()
        else:
            self.title.setText(env["name"])
            active = env["id"] == self.ctx.envs.active_id
            self.hint.setText("Active environment." if active else "Double-click the name in the list to rename.")
            self.table.set_rows(env["variables"])
            self.active_btn.setVisible(not active)

    def _store_rows(self):
        rows = [r for r in self.table.rows() if r["key"] or r["value"]]
        env = self._rows_target()
        if self._current == self.GLOBALS:
            self.ctx.envs.globals = rows
        elif env is not None:
            env["variables"] = rows
        self.ctx.envs.save()

    def _add(self):
        name, ok = QInputDialog.getText(self, "New environment", "Name:", text="Development")
        if ok and name.strip():
            env = self.ctx.envs.add(name.strip())
            self._fill(env["id"])

    def _duplicate(self):
        env = self._rows_target()
        if env is None:
            return
        dup = self.ctx.envs.add(env["name"] + " copy", [dict(r) for r in env["variables"]])
        self._fill(dup["id"])

    def _delete(self):
        env = self._rows_target()
        if env is None:
            return
        if QMessageBox.question(self, "Delete environment", f"Delete \"{env['name']}\"?") == \
                QMessageBox.StandardButton.Yes:
            self.ctx.envs.remove(env["id"])
            self._fill()

    def _rename(self):
        env = self._rows_target()
        if env is None:
            return
        name, ok = QInputDialog.getText(self, "Rename environment", "Name:", text=env["name"])
        if ok and name.strip():
            env["name"] = name.strip()
            self.ctx.envs.save()
            self._fill(env["id"])

    def _set_active(self):
        env = self._rows_target()
        if env is not None:
            self.ctx.envs.set_active(env["id"])
            self._fill(env["id"])

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import environment", "", "JSON (*.json);;All files (*)")
        if not path:
            return
        from core import importers
        try:
            res = importers.parse_file(path)
        except Exception as e:  # noqa: BLE001 - show parser error
            QMessageBox.warning(self, "Import failed", str(e))
            return
        if not res.environments:
            QMessageBox.information(self, "Import", "No environments found in this file.")
            return
        last = None
        for env in res.environments:
            last = self.ctx.envs.add(env["name"], env["variables"])
        self._fill(last["id"])

    def _export(self):
        env = self._rows_target()
        if env is None:
            env = {"name": "Globals", "variables": self.ctx.envs.globals}
        path, _ = QFileDialog.getSaveFileName(self, "Export environment",
                                              f"{env['name']}.postman_environment.json", "JSON (*.json)")
        if path:
            from core.importers.postman import export_environment
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_environment(env), f, indent=2, ensure_ascii=False)

    def done(self, result):
        self._store_rows()
        self.ctx.environments_changed.emit()
        super().done(result)


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        s = ctx.settings
        self.setWindowTitle("Settings")
        self.resize(640, 600)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        general = QWidget()
        gf = QFormLayout(general)
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(self.theme.findData(s["theme"]))
        gf.addRow("Theme", self.theme)
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Response below request", "vertical")
        self.layout_combo.addItem("Response beside request", "horizontal")
        self.layout_combo.setCurrentIndex(self.layout_combo.findData(s["layout"]))
        gf.addRow("Layout", self.layout_combo)
        self.font_size = QSpinBox()
        self.font_size.setRange(7, 24)
        self.font_size.setValue(int(s["editor_font_size"]))
        gf.addRow("Editor font size", self.font_size)
        self.history = QSpinBox()
        self.history.setRange(0, 5000)
        self.history.setValue(int(s["max_history_size"]))
        gf.addRow("History entries to keep", self.history)
        tabs.addTab(general, "General")

        network = QWidget()
        nf = QFormLayout(network)
        self.timeout = QSpinBox()
        self.timeout.setRange(0, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setSpecialValueText("No timeout")
        self.timeout.setValue(int(s["request_timeout"]))
        nf.addRow("Request timeout", self.timeout)
        self.max_mb = QSpinBox()
        self.max_mb.setRange(1, 2048)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setValue(int(s["max_response_mb"]))
        nf.addRow("Max response size", self.max_mb)
        self.verify = QCheckBox("Verify SSL certificates")
        self.verify.setChecked(bool(s["verify_ssl"]))
        nf.addRow("", self.verify)
        self.redirects = QCheckBox("Follow redirects automatically")
        self.redirects.setChecked(bool(s["follow_redirects"]))
        nf.addRow("", self.redirects)
        self.cookies = QCheckBox("Store and send cookies")
        self.cookies.setChecked(bool(s["send_cookies"]))
        clear = QPushButton("Clear cookies")
        clear.clicked.connect(lambda: (ctx.http.clear_cookies(), clear.setText("Cookies cleared")))
        crow = QHBoxLayout()
        crow.addWidget(self.cookies)
        crow.addStretch()
        crow.addWidget(clear)
        nf.addRow("", crow)
        self.proxy_mode = QComboBox()
        self.proxy_mode.addItem("Use system proxy settings", "system")
        self.proxy_mode.addItem("No proxy", "none")
        self.proxy_mode.addItem("Custom proxy", "custom")
        self.proxy_mode.setCurrentIndex(self.proxy_mode.findData(s["proxy_mode"]))
        nf.addRow("Proxy", self.proxy_mode)
        self.proxy_url = QLineEdit(s["proxy_url"])
        self.proxy_url.setPlaceholderText("http://user:pass@127.0.0.1:8080  or  socks5://127.0.0.1:1080")
        nf.addRow("Proxy URL", self.proxy_url)
        self.proxy_mode.currentIndexChanged.connect(
            lambda: self.proxy_url.setEnabled(self.proxy_mode.currentData() == "custom"))
        self.proxy_url.setEnabled(s["proxy_mode"] == "custom")
        tabs.addTab(network, "Network")

        headers_page = QWidget()
        hl = QVBoxLayout(headers_page)
        hint = QLabel("Sent with every request unless the request sets the same header.")
        hint.setObjectName("Dim")
        hl.addWidget(hint)
        self.default_headers = KeyValueTable(placeholders=("Header", "Value"),
                                             suggest_key=ctx.completion.suggest_header_keys,
                                             suggest_value=ctx.completion.suggest_header_values)
        self.default_headers.set_rows(s["default_headers"])
        hl.addWidget(self.default_headers)
        tabs.addTab(headers_page, "Default headers")

        data_page = QWidget()
        dl = QVBoxLayout(data_page)
        path = QLabel(f"Data folder: <code>{data_dir()}</code>")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setWordWrap(True)
        dl.addWidget(path)
        for text, slot in (("Open data folder", self._open_folder), ("Back up all data (ZIP)…", self._backup),
                           ("Restore from backup (ZIP)…", self._restore)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            dl.addWidget(b)
        dl.addStretch()
        tabs.addTab(data_page, "Data")

        lay.addWidget(tabs, 1)
        lay.addWidget(_buttons(self))

    def accept(self):
        self.ctx.settings.update({
            "theme": self.theme.currentData(), "layout": self.layout_combo.currentData(),
            "editor_font_size": self.font_size.value(), "max_history_size": self.history.value(),
            "request_timeout": self.timeout.value(), "max_response_mb": self.max_mb.value(),
            "verify_ssl": self.verify.isChecked(), "follow_redirects": self.redirects.isChecked(),
            "send_cookies": self.cookies.isChecked(), "proxy_mode": self.proxy_mode.currentData(),
            "proxy_url": self.proxy_url.text().strip(),
            "default_headers": [r for r in self.default_headers.rows() if r["key"]],
        })
        self.ctx.settings_changed.emit()
        super().accept()

    @staticmethod
    def _open_folder():
        QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir()))

    def _backup(self):
        default = f"getman_backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Back up data", default, "ZIP (*.zip)")
        if not path:
            return
        root = data_dir()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for folder, _dirs, files in os.walk(root):
                for name in files:
                    if name.endswith((".log", ".tmp")) or name.endswith(".log.1"):
                        continue
                    full = os.path.join(folder, name)
                    z.write(full, os.path.relpath(full, root))
        QMessageBox.information(self, "Backup", f"Saved to {path}")

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "ZIP (*.zip)")
        if not path:
            return
        if QMessageBox.question(self, "Restore", "Replace current collections, environments and history with "
                                "the backup? Restart Getman afterwards.") != QMessageBox.StandardButton.Yes:
            return
        root = os.path.realpath(data_dir())
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                name = member[5:] if member.startswith("data/") else member  # Getman 1.x backups
                target = os.path.realpath(os.path.join(root, name))
                if not target.startswith(root + os.sep) or member.endswith("/"):
                    continue  # skip path traversal and directories
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
        QMessageBox.information(self, "Restore", "Backup restored. Please restart Getman.")


class SaveRequestDialog(QDialog):
    """Pick a collection/folder and a name."""

    def __init__(self, ctx, name: str, parent=None, title: str = "Save request"):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(title)
        self.resize(460, 480)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.selectAll()
        form.addRow("Request name", self.name)
        lay.addLayout(form)
        label = QLabel("Save to")
        label.setObjectName("SectionTitle")
        lay.addWidget(label)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        lay.addWidget(self.tree, 1)
        new_col = QPushButton("+ New collection")
        new_col.clicked.connect(self._new_collection)
        row = QHBoxLayout()
        row.addWidget(new_col)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(_buttons(self))
        self._fill()

    def _fill(self, select: Optional[str] = None):
        self.tree.clear()
        first = None

        def add(parent_item, col_id, items):
            for it in items:
                if it.get("type") == "folder":
                    node = QTreeWidgetItem(parent_item, [it["name"] + " /"])
                    node.setData(0, Qt.ItemDataRole.UserRole, (col_id, it["id"]))
                    add(node, col_id, it["items"])

        for col in self.ctx.collections.collections:
            root = QTreeWidgetItem(self.tree, [col["name"]])
            root.setData(0, Qt.ItemDataRole.UserRole, (col["id"], None))
            add(root, col["id"], col["items"])
            first = first or root
            if select == col["id"]:
                first = root
        self.tree.expandAll()
        if first:
            self.tree.setCurrentItem(first)

    def _new_collection(self):
        name, ok = QInputDialog.getText(self, "New collection", "Collection name:")
        if ok and name.strip():
            col = self.ctx.collections.create(name.strip())
            self.ctx.collections_changed.emit()
            self._fill(col["id"])

    def accept(self):
        if not self.tree.currentItem() or not self.name.text().strip():
            QMessageBox.information(self, "Save", "Choose a collection (or create one) and enter a name.")
            return
        super().accept()

    def target(self) -> Tuple[str, Optional[str], str]:
        col_id, folder_id = self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        return col_id, folder_id, self.name.text().strip()


SHORTCUTS = [
    ("Ctrl+Enter", "Send request"), ("Esc", "Cancel running request"), ("Ctrl+T", "New tab"),
    ("Ctrl+W", "Close tab"), ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"),
    ("Ctrl+S", "Save request"), ("Ctrl+Shift+S", "Save as…"), ("Ctrl+L", "Focus URL"),
    ("Ctrl+P / Ctrl+K", "Quick open: requests, history, actions"), ("Ctrl+E", "Manage environments"),
    ("Ctrl+I", "Import"), ("Ctrl+Shift+C", "Copy as cURL"), ("Ctrl+F", "Find in response"),
    ("Ctrl+B", "Toggle sidebar"), ("Ctrl+,", "Settings"), ("Ctrl+Space", "Show suggestions in a field"),
    ("{{", "Variable autocomplete"), ("F2", "Rename in sidebar"), ("Middle click", "Open in new tab / close tab"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for i, (keys, what) in enumerate(SHORTCUTS):
            k = QLabel(f"<b>{keys}</b>")
            d = QLabel(what)
            d.setObjectName("Dim")
            grid.addWidget(k, i, 0)
            grid.addWidget(d, i, 1)
        lay.addLayout(grid)
        note = QLabel("On macOS use Cmd instead of Ctrl.")
        note.setObjectName("Faint")
        lay.addWidget(note)
        box = plain_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        box.rejected.connect(self.reject)
        lay.addWidget(box)
