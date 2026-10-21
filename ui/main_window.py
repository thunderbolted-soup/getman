"""Main window: top bar, sidebar, request tabs, shared editor + response view."""
import copy
import json
from typing import List, Optional

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSplitter, QTabBar, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from core.logger import get_logger
from core.models import new_id, new_request, normalize_request
from core.request_preparer import PrepareError, generate_curl, prepare_request
from core.session import load_session, save_session
from core.urlutil import split_url
from ui import theme
from ui.context import AppContext
from ui.icons import app_icon
from ui.request_editor import RequestEditor
from ui.response_view import ResponseView, format_console
from ui.sidebar import Sidebar

logger = get_logger()
MANAGE_ENVS = "__manage__"


def _fingerprint(request: dict) -> str:
    return json.dumps(request, sort_keys=True, ensure_ascii=False)


class TabDoc:
    """State of one open tab. Widgets are shared; a tab is just data."""

    def __init__(self, request: dict, origin: Optional[str] = None, snapshot: Optional[str] = None):
        self.uid = new_id()
        self.request = request
        self.origin = origin             # id of the saved request in a collection
        self.snapshot = snapshot if snapshot is not None else _fingerprint(request)
        self.response = None
        self.error: Optional[str] = None
        self.console = ""
        self.tests: list = []
        self.job = None
        self.prep = None
        self.local_vars: dict = {}

    @property
    def dirty(self) -> bool:
        return self.origin is not None and _fingerprint(self.request) != self.snapshot

    @property
    def pristine(self) -> bool:
        r = self.request
        return (self.origin is None and not r["url"] and self.response is None and self.job is None
                and r["body"]["mode"] == "none" and not r["headers"])

    def title(self) -> str:
        if self.origin or self.request["name"] not in ("New Request", ""):
            return self.request["name"]
        url = self.request["url"]
        if url:
            base, query, _ = split_url(url)
            short = base.split("://", 1)[-1]
            return short if len(short) <= 40 else "…" + short[-39:]
        return "New Request"


class VarsPopup(QFrame):
    """Quick look at every variable visible to the current tab."""

    def __init__(self, rows, on_manage, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popup")
        lay = QVBoxLayout(self)
        title = QLabel("Variables in scope")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Variable", "Value", "Scope"])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, (name, value, source) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(value))
            table.setItem(i, 2, QTableWidgetItem(source))
        lay.addWidget(table)
        if not rows:
            empty = QLabel("No variables yet. Add them to an environment or collection.")
            empty.setObjectName("Dim")
            lay.addWidget(empty)
        btn = QPushButton("Manage environments…")
        btn.clicked.connect(lambda: (self.close(), on_manage()))
        lay.addWidget(btn)
        self.resize(520, 340)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext = None):
        super().__init__()
        self.ctx = ctx or AppContext(self)
        # Style before building widgets, so they are polished once, not twice.
        theme.apply_theme(QApplication.instance(), self.ctx.settings["theme"])
        self.docs: List[TabDoc] = []
        self._current: Optional[TabDoc] = None
        self._var_cache = None
        self._switching = False
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1360, 860)

        central = QWidget()
        central.setObjectName("Workspace")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())

        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.setChildrenCollapsible(False)
        self.sidebar = Sidebar(self.ctx)
        self.sidebar.setMinimumWidth(220)
        self.main_split.addWidget(self.sidebar)

        workspace = QWidget()
        workspace.setObjectName("Workspace")
        wl = QVBoxLayout(workspace)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        tab_row = QWidget()
        tab_row.setObjectName("Card")
        tab_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tr = QHBoxLayout(tab_row)
        tr.setContentsMargins(0, 0, 6, 0)
        tr.setSpacing(0)
        self.tabbar = QTabBar()
        self.tabbar.setObjectName("DocTabs")
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabMoved.connect(self._on_tab_moved)
        self.tabbar.tabBarDoubleClicked.connect(lambda i: self.new_tab() if i < 0 else None)
        self.tabbar.customContextMenuRequested.connect(self._tab_menu)
        self.tabbar.installEventFilter(self)
        tr.addWidget(self.tabbar, 1)
        plus = QToolButton()
        plus.setText("＋")
        plus.setToolTip("New tab (Ctrl+T)")
        plus.clicked.connect(lambda: self.new_tab())
        tr.addWidget(plus)
        wl.addWidget(tab_row)

        self.editor = RequestEditor(self.ctx)
        self.response = ResponseView()
        self.work_split = QSplitter(Qt.Orientation.Vertical)
        self.work_split.setChildrenCollapsible(False)
        self.work_split.addWidget(self.editor)
        self.work_split.addWidget(self.response)
        self.work_split.setSizes([420, 420])
        wl.addWidget(self.work_split, 1)
        self.main_split.addWidget(workspace)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setSizes([290, 1070])
        root.addWidget(self.main_split, 1)
        self.setCentralWidget(central)

        self.editor.variables = self._variables
        self.editor.inherit_hint = self._inherit_hint
        self.editor.changed.connect(self._on_editor_changed)
        self.editor.send_clicked.connect(self.send_current)
        self.editor.save_clicked.connect(lambda: self.save_current())
        self.editor.save_as_clicked.connect(lambda: self.save_current(save_as=True))
        self.editor.curl_clicked.connect(self.copy_curl)
        self.editor.duplicate_clicked.connect(self.duplicate_current)
        self.editor.curl_pasted.connect(self._on_curl_pasted)
        self.response.cancel_clicked.connect(self.cancel_current)
        self.sidebar.collections.open_request.connect(self.open_saved)
        self.sidebar.history.open_entry.connect(self.open_history)
        self.sidebar.history.save_entry.connect(self._save_history_entry)
        self.sidebar.import_clicked.connect(lambda: self.import_dialog())
        self.sidebar.new_request_clicked.connect(lambda: self.new_tab())

        self.ctx.environments_changed.connect(self._on_vars_changed)
        self.ctx.collections_changed.connect(self._on_collections_changed)
        self.ctx.settings_changed.connect(self.apply_settings)

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(250)
        self._sync_timer.timeout.connect(self._sync_current)
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(3000)
        self._session_timer.timeout.connect(self.save_session)

        self._setup_shortcuts()
        self._refresh_envs()
        self.apply_settings()
        self._restore_session()
        logger.info("Getman started")

    # --- top bar -----------------------------------------------------------------
    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        toggle = QToolButton()
        toggle.setText("☰")
        toggle.setToolTip("Toggle sidebar (Ctrl+B)")
        toggle.clicked.connect(self.toggle_sidebar)
        lay.addWidget(toggle)
        brand = QLabel("Getman")
        brand.setObjectName("Brand")
        lay.addWidget(brand)
        lay.addStretch(1)
        search = QPushButton("⌕   Search requests, history, actions…        Ctrl+P")
        search.setMinimumWidth(380)
        search.setStyleSheet("text-align: left; padding: 6px 12px;")
        search.setCursor(Qt.CursorShape.PointingHandCursor)
        search.clicked.connect(self.open_palette)
        lay.addWidget(search)
        lay.addStretch(1)
        self.env_combo = QComboBox()
        self.env_combo.setObjectName("EnvCombo")
        self.env_combo.setToolTip("Active environment (Ctrl+E to manage)")
        self.env_combo.activated.connect(self._on_env_selected)
        lay.addWidget(self.env_combo)
        eye = QToolButton()
        eye.setText("👁")
        eye.setToolTip("Quick look at variables")
        eye.clicked.connect(lambda: self._show_vars_popup(eye))
        lay.addWidget(eye)
        settings = QToolButton()
        settings.setText("⚙")
        settings.setToolTip("Settings (Ctrl+,)")
        settings.clicked.connect(self.open_settings)
        lay.addWidget(settings)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Import…\tCtrl+I", lambda: self.import_dialog())
        menu.addAction("Manage environments…\tCtrl+E", self.manage_environments)
        menu.addSeparator()
        menu.addAction("Toggle response position", self.toggle_layout)
        menu.addAction("Toggle theme", self.toggle_theme)
        menu.addSeparator()
        menu.addAction("Keyboard shortcuts", self.show_shortcuts)
        menu.addAction("About Getman", self.show_about)
        more.setMenu(menu)
        lay.addWidget(more)
        return bar

    def _setup_shortcuts(self):
        def sc(keys, slot):
            for k in (keys if isinstance(keys, (list, tuple)) else [keys]):
                QShortcut(QKeySequence(k), self, slot)
        sc(["Ctrl+Return", "Ctrl+Enter"], self.send_current)
        sc("Ctrl+T", lambda: self.new_tab())
        sc("Ctrl+W", lambda: self.close_tab(self.tabbar.currentIndex()))
        sc("Ctrl+S", lambda: self.save_current())
        sc("Ctrl+Shift+S", lambda: self.save_current(save_as=True))
        sc("Ctrl+L", self.editor.focus_url)
        sc(["Ctrl+P", "Ctrl+K"], self.open_palette)
        sc("Ctrl+E", self.manage_environments)
        sc("Ctrl+I", lambda: self.import_dialog())
        sc("Ctrl+Shift+C", self.copy_curl)
        sc("Ctrl+F", self.response.open_find)
        sc("Ctrl+B", self.toggle_sidebar)
        sc("Ctrl+,", self.open_settings)
        sc("Ctrl+Tab", lambda: self._cycle_tab(1))
        sc("Ctrl+Shift+Tab", lambda: self._cycle_tab(-1))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._current and self._current.job:
            self.cancel_current()
            return
        super().keyPressEvent(e)

    # --- variables ---------------------------------------------------------------
    def _doc_collection(self, doc: Optional[TabDoc]):
        if doc is None:
            return None, ()
        return self.ctx.locate(doc.origin)

    def _variables(self):
        if self._var_cache is None:
            col, _ = self._doc_collection(self._current)
            self._var_cache = self.ctx.var_context(col).names()
        return self._var_cache

    def _inherit_hint(self) -> str:
        from core.request_preparer import effective_auth
        doc = self._current
        col, ancestors = self._doc_collection(doc)
        if col is None:
            return "Not saved in a collection — nothing to inherit, no auth will be sent."
        auth = effective_auth({"auth": {"type": "inherit"}}, ancestors)
        names = {"none": "no auth", "bearer": "Bearer token", "basic": "Basic auth", "apikey": "API key"}
        source = next((a["name"] for a in reversed(ancestors)
                       if (a.get("auth") or {}).get("type") not in (None, "inherit")), col["name"])
        return f"Inherits {names.get(auth['type'], auth['type'])} from \"{source}\"."

    def _on_vars_changed(self):
        self._var_cache = None
        self._refresh_envs()
        self.editor.refresh_highlight()

    def _on_collections_changed(self):
        self._var_cache = None
        for i, doc in enumerate(self.docs):
            if doc.origin:
                found = self.ctx.collections.find(doc.origin)
                if found is None:
                    doc.origin = None  # deleted from the sidebar: keep it as an unsaved tab
                elif found[1]["name"] != doc.request["name"]:
                    doc.request["name"] = found[1]["name"]
                    if doc is self._current:
                        self.editor.set_identity(doc.request["id"], found[1]["name"])
            self._update_tab(i)
        self.editor.refresh_highlight()

    # --- environments --------------------------------------------------------------
    def _refresh_envs(self):
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        self.env_combo.addItem("No environment", None)
        for env in self.ctx.envs.environments:
            self.env_combo.addItem(env["name"], env["id"])
        self.env_combo.insertSeparator(self.env_combo.count())
        self.env_combo.addItem("Manage environments…", MANAGE_ENVS)
        index = self.env_combo.findData(self.ctx.envs.active_id)
        self.env_combo.setCurrentIndex(max(index, 0))
        self.env_combo.blockSignals(False)
        env = self.ctx.envs.active()
        self.setWindowTitle(f"Getman — {env['name']}" if env else "Getman")

    def _on_env_selected(self, index):
        data = self.env_combo.itemData(index)
        if data == MANAGE_ENVS:
            self._refresh_envs()
            self.manage_environments()
            return
        self.switch_env(data)

    def switch_env(self, env_id):
        self.ctx.envs.set_active(env_id)
        self.ctx.environments_changed.emit()

    def manage_environments(self):
        from ui.dialogs import EnvironmentDialog
        dlg = EnvironmentDialog(self.ctx, self)
        dlg.exec()
        dlg.deleteLater()

    def _show_vars_popup(self, anchor):
        rows = [(n, v, s) for n, v, s in self._variables() if s != "dynamic"]
        popup = VarsPopup(rows, self.manage_environments, self)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        pos = anchor.mapToGlobal(QPoint(anchor.width() - popup.width(), anchor.height() + 4))
        popup.move(pos)
        popup.show()

    # --- tabs ------------------------------------------------------------------------
    def new_tab(self, request: dict = None, origin: Optional[str] = None, snapshot: str = None,
                activate: bool = True) -> TabDoc:
        doc = TabDoc(normalize_request(request) if request else new_request(), origin, snapshot)
        self.docs.append(doc)
        index = self.tabbar.addTab(doc.title())
        self._update_tab(index)
        if activate:
            self.tabbar.setCurrentIndex(index)
        self._session_timer.start()
        return doc

    def _update_tab(self, index: int):
        if not 0 <= index < len(self.docs):
            return
        doc = self.docs[index]
        method = doc.request["method"]
        short = {"DELETE": "DEL", "OPTIONS": "OPT"}.get(method, method)
        label = self.tabbar.tabButton(index, QTabBar.ButtonPosition.LeftSide)
        style = f"font-weight: 700; font-size: 10px; padding-right: 3px; color: {theme.method_color(method)};"
        if not isinstance(label, QLabel) or label.text() != short or label.property("theme") != theme.current():
            if label is not None:
                label.deleteLater()  # QTabBar doesn't delete replaced buttons
            label = QLabel(short)
            label.setStyleSheet(style)
            label.setProperty("theme", theme.current())
            label.ensurePolished()
            label.setFixedWidth(label.fontMetrics().horizontalAdvance(short) + 6)
            self.tabbar.setTabButton(index, QTabBar.ButtonPosition.LeftSide, label)
        if not isinstance(self.tabbar.tabButton(index, QTabBar.ButtonPosition.RightSide), QToolButton):
            close = QToolButton()
            close.setObjectName("TabClose")
            close.setText("✕")
            close.setToolTip("Close (Ctrl+W)")
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            close.clicked.connect(lambda _=False, b=close: self._close_by_button(b))
            self.tabbar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        title = doc.title() + ("  ●" if doc.dirty else "")
        if doc.job is not None:
            title = "⟳ " + title
        self.tabbar.setTabText(index, title)
        self.tabbar.setTabToolTip(index, f"{method} {doc.request['url']}" + ("\nUnsaved changes" if doc.dirty else ""))

    def _close_by_button(self, button):
        for i in range(self.tabbar.count()):
            if self.tabbar.tabButton(i, QTabBar.ButtonPosition.RightSide) is button:
                self.close_tab(i)
                return

    def _on_tab_changed(self, index: int):
        if self._switching or not 0 <= index < len(self.docs):
            return
        self._sync_current()
        doc = self.docs[index]
        self._current = doc
        self._var_cache = None
        self.editor.load(doc.request)
        self.editor.set_sending(doc.job is not None)
        self._show_doc_response(doc)
        if doc.origin:
            self.sidebar.collections.select_request(doc.origin)

    def _on_tab_moved(self, frm: int, to: int):
        doc = self.docs.pop(frm)
        self.docs.insert(to, doc)
        self._session_timer.start()

    def _cycle_tab(self, step: int):
        if self.tabbar.count() > 1:
            self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + step) % self.tabbar.count())

    def close_tab(self, index: int, ask: bool = True):
        if not 0 <= index < len(self.docs):
            return
        if index == self.tabbar.currentIndex():
            self._sync_current()
        doc = self.docs[index]
        if ask and doc.dirty:
            box = QMessageBox(self)
            box.setWindowTitle("Unsaved changes")
            box.setText(f"Save changes to \"{doc.title()}\" before closing?")
            box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                   | QMessageBox.StandardButton.Cancel)
            answer = box.exec()
            box.deleteLater()
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                self.tabbar.setCurrentIndex(index)
                if not self.save_current():
                    return
        if doc.job is not None:
            doc.job.cancel()
        self._switching = True
        self.docs.pop(index)
        if doc is self._current:
            self._current = None
        self.tabbar.removeTab(index)
        self._switching = False
        if not self.docs:
            self.new_tab()
        else:
            self._on_tab_changed(self.tabbar.currentIndex())
        self._session_timer.start()

    def _tab_menu(self, pos):
        index = self.tabbar.tabAt(pos)
        menu = QMenu(self)
        if index >= 0:
            menu.addAction("Close", lambda: self.close_tab(index))
            menu.addAction("Close others", lambda: self._close_many(lambda i: i != index))
            menu.addAction("Close tabs to the right", lambda: self._close_many(lambda i: i > index))
            menu.addAction("Duplicate", lambda: (self.tabbar.setCurrentIndex(index), self.duplicate_current()))
            menu.addSeparator()
        menu.addAction("New tab", lambda: self.new_tab())
        menu.addAction("Close all", lambda: self._close_many(lambda i: True))
        menu.exec(self.tabbar.mapToGlobal(pos))
        menu.deleteLater()

    def _close_many(self, predicate):
        for i in reversed(range(len(self.docs))):
            if predicate(i):
                self.close_tab(i)

    def eventFilter(self, obj, event):
        if obj is self.tabbar and event.type() == event.Type.MouseButtonRelease \
                and event.button() == Qt.MouseButton.MiddleButton:
            index = self.tabbar.tabAt(event.position().toPoint())
            if index >= 0:
                self.close_tab(index)
                return True
        return super().eventFilter(obj, event)

    # --- editor sync ------------------------------------------------------------------
    def _on_editor_changed(self):
        self._sync_timer.start()

    def _sync_current(self):
        self._sync_timer.stop()
        doc = self._current
        if doc is None or doc not in self.docs:
            return
        doc.request = self.editor.dump()
        self._update_tab(self.docs.index(doc))
        self._session_timer.start()

    def _show_doc_response(self, doc: TabDoc):
        if doc.job is not None:
            self.response.show_loading(doc.job.elapsed_ms())
        elif doc.response is not None:
            self.response.show_response(doc.response, doc.console, doc.tests)
        elif doc.error:
            self.response.show_error(doc.error, doc.console)
        else:
            self.response.show_empty()

    # --- opening ------------------------------------------------------------------------
    def _open_doc(self, request: dict, origin: Optional[str], new_tab: bool):
        if origin:
            for i, doc in enumerate(self.docs):
                if doc.origin == origin:
                    self.tabbar.setCurrentIndex(i)
                    return
        cur = self._current
        if not new_tab and cur is not None:
            self._sync_current()
        if not new_tab and cur is not None and cur.pristine:
            index = self.docs.index(cur)
            self.docs[index] = TabDoc(normalize_request(request), origin)
            self._current = None
            self._update_tab(index)
            self._on_tab_changed(index)
            return
        self.new_tab(request, origin)

    def open_saved(self, col_id: str, req_id: str, new_tab: bool = False):
        found = self.ctx.collections.find(req_id)
        if found:
            self._open_doc(copy.deepcopy(found[1]), req_id, new_tab)

    def open_history(self, entry: dict, new_tab: bool = False):
        req = copy.deepcopy(entry["request"])
        req["id"] = new_id()
        if req["name"] == "New Request" or not req["name"]:
            req["name"] = "New Request"
        self._open_doc(req, None, new_tab)

    def duplicate_current(self):
        self._sync_current()
        if self._current:
            req = copy.deepcopy(self._current.request)
            req["id"] = new_id()
            if self._current.origin:
                req["name"] += " copy"
            self.new_tab(req)

    def _on_curl_pasted(self, text: str):
        from core.importers import ImportError_
        from core.importers.curl import parse_curl
        try:
            req = parse_curl(text)
        except ImportError_ as e:
            QMessageBox.warning(self, "cURL", str(e))
            return
        self._sync_current()
        doc = self._current
        if doc is None:
            return
        keep = {"id": doc.request["id"], "name": doc.request["name"], "scripts": doc.request["scripts"]}
        if not doc.origin:
            keep["name"] = "New Request"
        req.update(keep)
        doc.request = normalize_request(req)
        self.editor.load(doc.request)
        self._update_tab(self.docs.index(doc))

    # --- sending -------------------------------------------------------------------------
    def send_current(self):
        self._sync_current()
        doc = self._current
        if doc is None:
            return
        if doc.job is not None:
            self.cancel_current()
            return
        col, ancestors = self._doc_collection(doc)
        var_ctx = self.ctx.var_context(col)
        try:
            prep = prepare_request(doc.request, var_ctx, ancestors=ancestors,
                                   default_headers=self.ctx.settings["default_headers"])
        except PrepareError as e:
            doc.response, doc.error, doc.console = None, str(e), ""
            self._show_doc_response(doc)
            self.editor.focus_url()
            return
        if prep.script is not None:
            self.ctx.apply_script_env(prep.script.env_changes, prep.script.env_removed)
        try:
            job = self.ctx.http.send(prep)
        except ValueError as e:
            doc.response, doc.error = None, str(e)
            doc.console = format_console(prep, error=str(e))
            self._show_doc_response(doc)
            return
        doc.job, doc.prep, doc.local_vars = job, prep, dict(var_ctx.layers["local"])
        doc.error = None
        job.finished.connect(lambda resp, d=doc: self._on_finished(d, resp))
        job.failed.connect(lambda msg, d=doc: self._on_failed(d, msg))
        job.cancelled.connect(lambda d=doc: self._on_failed(d, "cancelled"))
        self._update_tab(self.docs.index(doc))
        if doc is self._current:
            self.editor.set_sending(True)
            self.response.show_loading()

    def cancel_current(self):
        doc = self._current
        if doc is not None and doc.job is not None:
            doc.job.cancel()

    def _finish(self, doc: TabDoc):
        doc.job = None
        doc.prep = None
        if doc in self.docs:
            self._update_tab(self.docs.index(doc))
        if doc is self._current:
            self.editor.set_sending(False)
            self._show_doc_response(doc)

    def _on_finished(self, doc: TabDoc, resp):
        post = None
        code = doc.request["scripts"]["post"]
        if code.strip():
            from core.scripting import run_post_script
            col, _ = self._doc_collection(doc)
            flat = self.ctx.var_context(col, local=doc.local_vars).as_flat_dict()
            post = run_post_script(code, resp, flat, doc.local_vars)
            self.ctx.apply_script_env(post.env_changes, post.env_removed)
        doc.response, doc.error = resp, None
        doc.tests = post.tests if post else []
        doc.console = format_console(doc.prep, resp, post_script=post)
        self.ctx.history.add(doc.request, resp.status, resp.elapsed_ms, resp.size)
        self.ctx.history_changed.emit()
        self._finish(doc)

    def _on_failed(self, doc: TabDoc, message: str):
        doc.response, doc.error, doc.tests = None, message, []
        doc.console = format_console(doc.prep, error=None if message == "cancelled" else message)
        if message != "cancelled":
            self.ctx.history.add(doc.request, None, None, error=message)
            self.ctx.history_changed.emit()
        self._finish(doc)

    def copy_curl(self):
        self._sync_current()
        doc = self._current
        if doc is None:
            return
        col, ancestors = self._doc_collection(doc)
        try:
            # scripts run here too, so the command matches what Send would do
            prep = prepare_request(doc.request, self.ctx.var_context(col), ancestors=ancestors,
                                   default_headers=self.ctx.settings["default_headers"])
        except PrepareError as e:
            QMessageBox.information(self, "Copy as cURL", str(e))
            return
        QGuiApplication.clipboard().setText(generate_curl(prep))
        self.statusBar().showMessage("cURL command copied to clipboard (variables resolved)", 3000)

    # --- saving ---------------------------------------------------------------------------
    def save_current(self, save_as: bool = False) -> bool:
        self._sync_current()
        doc = self._current
        if doc is None:
            return False
        found = self.ctx.collections.find(doc.origin) if doc.origin else None
        if found and not save_as:
            col, item, _ = found
            item.clear()
            item.update(copy.deepcopy(doc.request))
            self.ctx.collections.save(col)
        else:
            from ui.dialogs import SaveRequestDialog
            name = doc.request["name"]
            if name in ("New Request", "") and doc.request["url"]:
                name = doc.title()
            dlg = SaveRequestDialog(self.ctx, name, self, "Save as" if save_as else "Save request")
            accepted = dlg.exec()
            dlg.deleteLater()
            if not accepted:
                return False
            col_id, folder_id, name = dlg.target()
            col = self.ctx.collections.get(col_id)
            if col is None:
                return False
            parent = col if folder_id is None else self.ctx.collections.find(folder_id)[1]
            req = copy.deepcopy(doc.request)
            req["id"], req["name"] = new_id(), name
            parent["items"].append(req)
            self.ctx.collections.save(col)
            doc.request, doc.origin = req, req["id"]
            self.editor.set_identity(req["id"], name)
            self.sidebar.collections._expanded.update({col_id, folder_id or col_id})
        doc.snapshot = _fingerprint(doc.request)
        self.ctx.collections_changed.emit()
        self._update_tab(self.docs.index(doc))
        self.statusBar().showMessage("Saved", 2000)
        return True

    def _save_history_entry(self, entry: dict):
        self.open_history(entry, new_tab=True)
        self.save_current(save_as=True)

    # --- dialogs ----------------------------------------------------------------------------
    def import_dialog(self, path: str = None, text: str = None):
        from ui.import_dialog import ImportDialog
        dlg = ImportDialog(self.ctx, self, path=path, text=text)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if dlg.exec():
            for req in dlg.opened_requests:
                self.new_tab(req)
            if dlg.imported_collections:
                for col in dlg.imported_collections:
                    self.sidebar.collections._expanded.add(col["id"])
                self.sidebar.collections.refresh()
                self.statusBar().showMessage(f"Imported {len(dlg.imported_collections)} collection(s)", 4000)

    def open_settings(self):
        from ui.dialogs import SettingsDialog
        dlg = SettingsDialog(self.ctx, self)
        dlg.exec()
        dlg.deleteLater()

    def show_shortcuts(self):
        from ui.dialogs import ShortcutsDialog
        dlg = ShortcutsDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def show_about(self):
        from core.paths import data_dir
        QMessageBox.about(self, "About Getman",
                          "<h3>Getman 2.0</h3><p>A fast, local-only HTTP client.<br>No accounts, no cloud: "
                          f"everything is stored in<br><code>{data_dir()}</code></p>")

    def open_palette(self):
        from ui.palette import CommandPalette
        actions = [
            ("New request", "Ctrl+T", lambda: self.new_tab()),
            ("Import…", "Ctrl+I", lambda: self.import_dialog()),
            ("Manage environments", "Ctrl+E", self.manage_environments),
            ("Settings", "Ctrl+,", self.open_settings),
            ("Copy as cURL", "Ctrl+Shift+C", self.copy_curl),
            ("Save request", "Ctrl+S", lambda: self.save_current()),
            ("Toggle theme", "", self.toggle_theme),
            ("Toggle response position", "", self.toggle_layout),
            ("Toggle sidebar", "Ctrl+B", self.toggle_sidebar),
            ("Show history", "", self.sidebar.show_history),
            ("Keyboard shortcuts", "", self.show_shortcuts),
        ]
        palette = CommandPalette(self.ctx, actions, lambda c, r: self.open_saved(c, r),
                                 lambda e: self.open_history(e), self.switch_env, self)
        palette.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        palette.popup_over(self)

    # --- view ---------------------------------------------------------------------------------
    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self._session_timer.start()

    def toggle_layout(self):
        layout = "horizontal" if self.ctx.settings["layout"] == "vertical" else "vertical"
        self.ctx.settings.update({"layout": layout})
        self.ctx.settings_changed.emit()

    def toggle_theme(self):
        self.ctx.settings.update({"theme": "light" if self.ctx.settings["theme"] == "dark" else "dark"})
        self.ctx.settings_changed.emit()

    def apply_settings(self):
        s = self.ctx.settings
        if theme.current() != s["theme"]:
            theme.apply_theme(QApplication.instance(), s["theme"])
            self.editor.reload_theme()
            self.response.reload_theme()
            self.sidebar.collections.viewport().update()
            self.sidebar.history.refresh()
            for i in range(len(self.docs)):
                self._update_tab(i)
            if self._current is not None:
                self._show_doc_response(self._current)
        orientation = Qt.Orientation.Horizontal if s["layout"] == "horizontal" else Qt.Orientation.Vertical
        if self.work_split.orientation() != orientation:
            self.work_split.setOrientation(orientation)
            total = sum(self.work_split.sizes()) or 800
            self.work_split.setSizes([total // 2, total - total // 2])
        size = int(s["editor_font_size"])
        self.editor.set_editor_font_size(size)
        self.response.set_editor_font_size(size)

    # --- drag & drop import -----------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.import_dialog(path=url.toLocalFile())
                break

    # --- session ------------------------------------------------------------------------------------
    def save_session(self):
        self._sync_current()
        tabs = []
        for doc in self.docs:
            tabs.append({"request": doc.request, "origin": doc.origin, "dirty": doc.dirty})
        save_session({
            "tabs": tabs, "active": self.tabbar.currentIndex(),
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "main_split": self.main_split.sizes(), "work_split": self.work_split.sizes(),
            "sidebar": self.sidebar.isVisible(),
            "expanded": sorted(self.sidebar.collections._expanded),
        })

    def _restore_session(self):
        data = load_session()
        if data.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(data["geometry"].encode()))
        if isinstance(data.get("main_split"), list) and len(data["main_split"]) == 2:
            self.main_split.setSizes(data["main_split"])
        if isinstance(data.get("work_split"), list) and len(data["work_split"]) == 2 and all(data["work_split"]):
            self.work_split.setSizes(data["work_split"])
        self.sidebar.setVisible(data.get("sidebar", True))
        self.sidebar.collections._expanded.update(data.get("expanded") or [])
        self.sidebar.collections.refresh()
        for tab in data.get("tabs") or []:
            if not isinstance(tab, dict) or not isinstance(tab.get("request"), dict):
                continue
            req = normalize_request(tab["request"])
            origin = tab.get("origin")
            found = self.ctx.collections.find(origin) if origin else None
            if origin and not found:
                origin = None
            if found and not tab.get("dirty"):
                req = normalize_request(copy.deepcopy(found[1]))
            snapshot = _fingerprint(normalize_request(copy.deepcopy(found[1]))) if found else None
            self.new_tab(req, origin, snapshot, activate=False)
        if not self.docs:
            self.new_tab()
        active = data.get("active", 0)
        active = active if isinstance(active, int) and 0 <= active < len(self.docs) else 0
        if self.tabbar.currentIndex() != active:
            self.tabbar.setCurrentIndex(active)
        else:
            self._on_tab_changed(active)

    def closeEvent(self, e):
        for doc in self.docs:
            if doc.job is not None:
                doc.job.cancel()
        self.save_session()
        super().closeEvent(e)
