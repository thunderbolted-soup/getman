"""Universal import: drop a file, paste text or fetch a URL. The format is
detected automatically and the content is previewed as a checkable tree so
only the wanted requests (e.g. a few endpoints of a large OpenAPI spec) are
imported."""
import copy
import os
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core import importers
from core.models import count_requests, normalize_collection
from core.request_preparer import PreparedRequest
from ui import theme

KIND = Qt.ItemDataRole.UserRole


class DropZone(QWidget):
    file_dropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)
        lay = QVBoxLayout(self)
        title = QLabel("Drop a file here or click to browse")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: 600;")
        sub = QLabel("Postman · Insomnia · OpenAPI / Swagger (JSON, YAML) · HAR · .http · cURL · Getman")
        sub.setObjectName("Dim")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, e):
        self.clicked.emit()

    def _hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.file_dropped.emit(url.toLocalFile())
                break


class ImportDialog(QDialog):
    def __init__(self, ctx, parent=None, path: str = None, text: str = None):
        super().__init__(parent)
        self.ctx = ctx
        self.result_data: Optional[importers.ImportResult] = None
        self.opened_requests: List[dict] = []
        self.imported_collections: List[dict] = []
        self._job = None
        self.setWindowTitle("Import")
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.drop = DropZone()
        self.drop.clicked.connect(self._browse)
        self.drop.file_dropped.connect(self.load_file)
        lay.addWidget(self.drop)

        url_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("…or a link to an OpenAPI spec / collection, e.g. https://petstore3.swagger.io/api/v3/openapi.json")
        self.url.returnPressed.connect(self._fetch)
        fetch = QPushButton("Fetch")
        fetch.clicked.connect(self._fetch)
        url_row.addWidget(self.url, 1)
        url_row.addWidget(fetch)
        lay.addLayout(url_row)

        split = QSplitter(Qt.Orientation.Vertical)
        paste_box = QWidget()
        pl = QVBoxLayout(paste_box)
        pl.setContentsMargins(0, 0, 0, 0)
        self.paste = QPlainTextEdit()
        self.paste.setFont(theme.mono_font())
        self.paste.setPlaceholderText("…or paste text here: a cURL command, JSON/YAML export, .http file")
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(350)
        self._parse_timer.timeout.connect(self._parse_pasted)
        self.paste.textChanged.connect(lambda: self._parse_timer.start())
        pl.addWidget(self.paste)
        split.addWidget(paste_box)

        preview = QWidget()
        vl = QVBoxLayout(preview)
        vl.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Nothing loaded yet.")
        self.summary.setObjectName("Dim")
        self.summary.setWordWrap(True)
        vl.addWidget(self.summary)
        filter_row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter requests…")
        self.filter.textChanged.connect(self._apply_filter)
        all_btn, none_btn = QPushButton("Select all"), QPushButton("Select none")
        all_btn.setObjectName("Link")
        none_btn.setObjectName("Link")
        all_btn.clicked.connect(lambda: self._check_all(True))
        none_btn.clicked.connect(lambda: self._check_all(False))
        filter_row.addWidget(self.filter, 1)
        filter_row.addWidget(all_btn)
        filter_row.addWidget(none_btn)
        vl.addLayout(filter_row)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.itemChanged.connect(self._update_button)
        vl.addWidget(self.tree, 1)
        split.addWidget(preview)
        split.setSizes([140, 400])
        lay.addWidget(split, 1)

        from ui.dialogs import plain_buttons
        self.buttons = plain_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                                      | QDialogButtonBox.StandardButton.Cancel))
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setObjectName("Primary")
        self.ok.setText("Import")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self._do_import)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.filter, self.tree):
            w.setEnabled(False)
        if path:
            QTimer.singleShot(0, lambda: self.load_file(path))
        elif text:
            self.paste.setPlainText(text)

    # --- loading ---------------------------------------------------------------------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import file", "",
            "Supported files (*.json *.yaml *.yml *.har *.http *.rest *.txt *.sh);;All files (*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        try:
            self._show(importers.parse_file(path), os.path.basename(path))
        except Exception as e:  # noqa: BLE001 - user-facing parse errors
            self._fail(str(e))

    def _parse_pasted(self):
        text = self.paste.toPlainText()
        if not text.strip():
            return
        try:
            self._show(importers.parse_text(text), "pasted text")
        except Exception as e:  # noqa: BLE001
            self._fail(str(e))

    def _fetch(self):
        url = self.url.text().strip()
        if not url:
            return
        prep = PreparedRequest()
        prep.url = url if "://" in url else "https://" + url
        prep.headers = [("Accept", "application/json, application/yaml, text/yaml, */*"), ("User-Agent", "Getman/2.0")]
        try:
            self._job = self.ctx.http.send(prep)
        except ValueError as e:
            self._fail(str(e))
            return
        self.summary.setText("Downloading…")
        self._job.finished.connect(lambda resp: self._on_fetched(resp, url))
        self._job.failed.connect(self._fail)

    def _on_fetched(self, resp, url):
        if resp.status >= 400:
            self._fail(f"Server answered {resp.status} {resp.reason}")
            return
        name = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
        try:
            self._show(importers.parse_text(resp.body.decode("utf-8", errors="replace"), name), url)
        except Exception as e:  # noqa: BLE001
            self._fail(str(e))

    def _fail(self, message: str):
        self.result_data = None
        self.tree.clear()
        self.summary.setText(f"<span style='color:{theme.color('danger')}'>{message}</span>")
        self.ok.setEnabled(False)

    # --- preview tree ------------------------------------------------------------------
    def _show(self, res: importers.ImportResult, source: str):
        self.result_data = res
        warnings = "".join(f"<br>Warning: {w}" for w in res.warnings)
        self.summary.setText(f"<b>{res.kind}</b> from {source}: {res.summary()}{warnings}")
        self.tree.blockSignals(True)
        self.tree.clear()
        for ci, col in enumerate(res.collections):
            root = QTreeWidgetItem(self.tree, [f"{col['name']}  ({count_requests(col)} requests)"])
            root.setData(0, KIND, ("collection", ci))
            root.setFlags(root.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            root.setCheckState(0, Qt.CheckState.Checked)
            self._add_items(root, col["items"])
            root.setExpanded(True)
        for ei, env in enumerate(res.environments):
            item = QTreeWidgetItem(self.tree, [f"Environment: {env['name']}  ({len(env['variables'])} variables)"])
            item.setData(0, KIND, ("environment", ei))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
        for ri, req in enumerate(res.requests):
            item = QTreeWidgetItem(self.tree, [f"{req['method']}  {req['url']}  — opens in a new tab"])
            item.setData(0, KIND, ("request", ri))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        for w in (self.filter, self.tree):
            w.setEnabled(True)
        self._update_button()

    def _add_items(self, parent: QTreeWidgetItem, items):
        for it in items:
            if it.get("type") == "folder":
                node = QTreeWidgetItem(parent, [f"{it['name']} /"])
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                node.setCheckState(0, Qt.CheckState.Checked)
                node.setData(0, KIND, ("folder", it["id"]))
                self._add_items(node, it["items"])
            else:
                node = QTreeWidgetItem(parent, [f"{it['method']:<7} {it['name']}"])
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                node.setCheckState(0, Qt.CheckState.Checked)
                node.setData(0, KIND, ("item", it["id"]))
                node.setToolTip(0, it["url"])
                node.setFont(0, theme.mono_font())

    def _apply_filter(self, text: str):
        text = text.lower()

        def visit(item) -> bool:
            match = not text or text in item.text(0).lower() or text in (item.toolTip(0) or "").lower()
            child = False
            for i in range(item.childCount()):
                child = visit(item.child(i)) or child
            item.setHidden(not (match or child))
            return match or child

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _check_all(self, on: bool):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not item.isHidden():
                item.setCheckState(0, state)

    def _update_button(self, *_):
        any_checked = any(self.tree.topLevelItem(i).checkState(0) != Qt.CheckState.Unchecked
                          for i in range(self.tree.topLevelItemCount()))
        self.ok.setEnabled(bool(self.result_data) and any_checked)

    # --- import --------------------------------------------------------------------------
    def _selected_ids(self, root: QTreeWidgetItem) -> set:
        ids = set()

        def visit(item):
            kind = item.data(0, KIND)
            if kind and kind[0] == "item" and item.checkState(0) == Qt.CheckState.Checked:
                ids.add(kind[1])
            for i in range(item.childCount()):
                visit(item.child(i))
        visit(root)
        return ids

    @staticmethod
    def _prune(items, keep: set) -> list:
        out = []
        for it in items:
            if it.get("type") == "folder":
                it = dict(it, items=ImportDialog._prune(it["items"], keep))
                if it["items"]:
                    out.append(it)
            elif it["id"] in keep:
                out.append(it)
        return out

    def _do_import(self):
        res = self.result_data
        if res is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            kind, index = root.data(0, KIND)
            if root.checkState(0) == Qt.CheckState.Unchecked:
                continue
            if kind == "collection":
                col = copy.deepcopy(res.collections[index])
                col["items"] = self._prune(col["items"], self._selected_ids(root))
                self.imported_collections.append(self.ctx.collections.add(normalize_collection(col)))
            elif kind == "environment":
                env = res.environments[index]
                self.ctx.envs.add(env["name"], env["variables"])
            elif kind == "request":
                self.opened_requests.append(res.requests[index])
        if self.imported_collections:
            self.ctx.collections_changed.emit()
        if res.environments:
            self.ctx.environments_changed.emit()
        self.accept()
