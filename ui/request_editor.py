"""Request editor: URL bar + Params / Headers / Body / Auth / Scripts / Notes.

One editor instance is shared by all tabs (tabs only keep request dicts),
so memory doesn't grow with the number of open tabs."""
import copy
import json
import re
from typing import Callable, List, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QPushButton, QSplitter, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from core.models import METHODS, kv, new_request
from core.urlutil import parse_query, path_variables, replace_query, split_url
from ui import theme
from ui.auth_editor import AuthEditor
from ui.code_editor import CodeEditor
from ui.fields import SmartLineEdit
from ui.kv_table import KeyValueTable

BODY_MODES = [("none", "None"), ("json", "JSON"), ("xml", "XML"), ("text", "Text"), ("form", "Form Data"),
              ("urlencoded", "URL Encoded"), ("binary", "Binary"), ("graphql", "GraphQL")]

PRE_SNIPPETS = [
    ("Set an environment variable", 'env["key"] = "value"\n'),
    ("Add a timestamp header", 'request.headers["X-Timestamp"] = str(int(time.time()))\n'),
    ("Sign body with HMAC-SHA256",
     'secret = env.get("secret", "")\n'
     'signature = hmac.new(secret.encode(), (request.body or "").encode(), hashlib.sha256).hexdigest()\n'
     'request.headers["X-Signature"] = signature\n'),
    ("Generate a request id", 'variables["requestId"] = str(uuid.uuid4())\n'),
]
POST_SNIPPETS = [
    ("Save token from JSON response", 'env["token"] = response.json()["access_token"]\n'),
    ("Test: status code is 200", 'test("status is 200", response.status == 200)\n'),
    ("Test: response time < 500 ms", 'test("faster than 500 ms", response.elapsed_ms < 500)\n'),
    ("Test: JSON has field", 'test("has id", "id" in response.json())\n'),
    ("Log response header", 'log(response.header("Content-Type"))\n'),
]
SCRIPT_HELP = ("Python. <b>env</b> — variables (assignments are saved to the active environment), "
               "<b>variables</b> — this request only, <b>request</b> (pre) / <b>response</b> (post), "
               "<b>test(name, condition)</b>, <b>log()</b>. Modules: json, re, time, datetime, hashlib, hmac, "
               "base64, uuid, random.")

_VAR_ANY = re.compile(r"\{\{[^{}]*\}\}")


def beautify_json(text: str) -> str:
    """Pretty-prints JSON that may contain {{variables}} (quoted or bare)."""
    originals: List[str] = []
    out = []
    in_string = escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if text.startswith("{{", i):
            m = _VAR_ANY.match(text, i)
            if m:
                originals.append(m.group(0))
                n = len(originals) - 1
                out.append(f"__GV{n}__" if in_string else f'"__GVQ{n}__"')
                i = m.end()
                continue
        out.append(ch)
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        i += 1
    pretty = json.dumps(json.loads("".join(out)), indent=2, ensure_ascii=False)
    for n, original in enumerate(originals):
        pretty = pretty.replace(f'"__GVQ{n}__"', original).replace(f"__GV{n}__", original)
    return pretty


def beautify_xml(text: str) -> str:
    from xml.dom import minidom
    pretty = minidom.parseString(text.encode("utf-8")).toprettyxml(indent="  ")
    lines = [ln for ln in pretty.splitlines() if ln.strip()]
    if lines and lines[0].startswith("<?xml") and not text.lstrip().startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(lines)


class Segmented(QWidget):
    """Row of checkable tool buttons acting like a segmented control."""
    changed = Signal(str)

    def __init__(self, options: List[Tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for key, label in options:
            btn = QToolButton()
            btn.setObjectName("Segment")
            btn.setText(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            lay.addWidget(btn)

    def set_value(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def value(self) -> str:
        for key, btn in self.buttons.items():
            if btn.isChecked():
                return key
        return next(iter(self.buttons))


class RequestEditor(QWidget):
    changed = Signal()
    send_clicked = Signal()
    save_clicked = Signal()
    save_as_clicked = Signal()
    curl_clicked = Signal()
    duplicate_clicked = Signal()
    curl_pasted = Signal(str)

    SECTIONS = ("params", "headers", "body", "auth", "scripts", "notes")

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._request = new_request()
        self._loading = False
        self._syncing = False
        self._built = set()
        self._code_editors: List[CodeEditor] = []
        self._kv_tables: List[KeyValueTable] = []
        self.variables: Callable = lambda: []
        self.inherit_hint: Callable[[], str] = lambda: ""
        self._var_provider = lambda: self.variables()  # late-bound: changes with the active tab
        self._known = lambda: {n for n, _, _ in self.variables()}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 0)
        lay.setSpacing(8)
        lay.addLayout(self._build_url_bar())

        # Sections are built the first time their tab is opened; until then
        # their data simply stays in self._request (saves memory and startup time).
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self._holders = {}
        for name in self.SECTIONS:
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 8, 0, 0)
            self._holders[name] = holder
            self.tabs.addTab(holder, name.capitalize())
        self.tabs.currentChanged.connect(self._on_tab_changed)
        lay.addWidget(self.tabs, 1)
        self._ensure("params")

        self._label_timer = QTimer(self)
        self._label_timer.setSingleShot(True)
        self._label_timer.setInterval(150)
        self._label_timer.timeout.connect(self._update_tab_labels)
        self._on_method("GET")

    # --- construction ----------------------------------------------------------------
    def _build_url_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.url_frame = QWidget()
        self.url_frame.setObjectName("UrlBar")
        self.url_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ul = QHBoxLayout(self.url_frame)
        ul.setContentsMargins(2, 0, 4, 0)
        ul.setSpacing(0)
        self.method = QComboBox()
        self.method.setObjectName("MethodCombo")
        self.method.addItems(METHODS)
        self.method.setFixedWidth(104)
        self.method.currentTextChanged.connect(self._on_method)
        ul.addWidget(self.method)
        self._url_sep = QWidget()
        self._url_sep.setFixedWidth(1)
        self._url_sep.setStyleSheet(f"background: {theme.color('border')};")
        ul.addWidget(self._url_sep)
        self.url = SmartLineEdit(variables=self._var_provider, suggest=self.ctx.completion.suggest_urls,
                                 paste_handler=self._handle_paste)
        self.url.setObjectName("UrlEdit")
        self.url.setPlaceholderText("Enter URL or paste a cURL command   (Ctrl+L)")
        self.url.textChanged.connect(self._on_url_changed)
        self.url.returnPressed.connect(self._on_url_return)
        ul.addWidget(self.url, 1)
        bar.addWidget(self.url_frame, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setMinimumWidth(92)
        self.send_btn.setToolTip("Send request (Ctrl+Enter)")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self.send_clicked)
        bar.addWidget(self.send_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setToolTip("Save to collection (Ctrl+S)")
        self.save_btn.clicked.connect(self.save_clicked)
        bar.addWidget(self.save_btn)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("More actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Copy as cURL\tCtrl+Shift+C", self.curl_clicked.emit)
        menu.addAction("Save as…\tCtrl+Shift+S", self.save_as_clicked.emit)
        menu.addAction("Duplicate in new tab", self.duplicate_clicked.emit)
        more.setMenu(menu)
        bar.addWidget(more)
        return bar

    def _kv(self, **kwargs) -> KeyValueTable:
        table = KeyValueTable(variables=self._var_provider, **kwargs)
        self._kv_tables.append(table)
        return table

    def _code(self, language: str) -> CodeEditor:
        editor = CodeEditor(language, known_vars=self._known)
        editor.set_font_size(int(self.ctx.settings["editor_font_size"]))
        self._code_editors.append(editor)
        return editor

    def _ensure(self, name: str):
        if name in self._built:
            return
        self._built.add(name)
        was_loading = self._loading
        self._loading = True
        widget = getattr(self, f"_build_{name}")()
        self._holders[name].layout().addWidget(widget)
        self._load_section(name, self._request)
        self._loading = was_loading

    def _build_params(self) -> QWidget:
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        self.params = self._kv(suggest_key=self.ctx.completion.suggest_param_keys,
                               suggest_value=self.ctx.completion.suggest_param_values,
                               placeholders=("Parameter", "Value"))
        self.params.changed.connect(self._on_params_changed)
        pl.addWidget(self.params, 3)
        self.path_label = QLabel("Path Variables")
        self.path_label.setObjectName("SectionTitle")
        pl.addWidget(self.path_label)
        self.path_vars = self._kv(allow_add=False, key_editable=False, checkable=False,
                                  placeholders=("Variable", "Value"))
        self.path_vars.changed.connect(self._emit_changed)
        pl.addWidget(self.path_vars, 2)
        return page

    def _build_headers(self) -> QWidget:
        self.headers = self._kv(suggest_key=self.ctx.completion.suggest_header_keys,
                                suggest_value=self.ctx.completion.suggest_header_values,
                                placeholders=("Header", "Value"))
        self.headers.changed.connect(self._emit_changed)
        return self.headers

    def _build_body(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.body_mode = Segmented(BODY_MODES)
        self.body_mode.changed.connect(self._on_body_mode)
        top.addWidget(self.body_mode)
        top.addStretch()
        self.beautify_btn = QPushButton("Beautify")
        self.beautify_btn.setObjectName("Link")
        self.beautify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.beautify_btn.clicked.connect(self.beautify)
        top.addWidget(self.beautify_btn)
        lay.addLayout(top)

        self.body_stack = QStackedWidget()
        none = QLabel("This request has no body.")
        none.setObjectName("Faint")
        none.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_stack.addWidget(none)
        text_page = QWidget()
        tl = QVBoxLayout(text_page)
        tl.setContentsMargins(0, 0, 0, 0)
        self.body_text = self._code("json")
        self.body_text.textChanged.connect(self._emit_changed)
        self.body_error = QLabel("")
        self.body_error.setStyleSheet(f"color: {theme.color('danger')};")
        self.body_error.hide()
        self.body_text.validity_changed.connect(self._on_body_validity)
        tl.addWidget(self.body_text)
        tl.addWidget(self.body_error)
        self.body_stack.addWidget(text_page)
        self.form = self._kv(with_type=True, placeholders=("Field", "Value"))
        self.form.changed.connect(self._emit_changed)
        self.body_stack.addWidget(self.form)
        self.urlencoded = self._kv(placeholders=("Field", "Value"))
        self.urlencoded.changed.connect(self._emit_changed)
        self.body_stack.addWidget(self.urlencoded)
        binary = QWidget()
        bl = QVBoxLayout(binary)
        bl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.binary_path = SmartLineEdit(variables=self._var_provider)
        self.binary_path.setPlaceholderText("Path to the file to send as the request body")
        self.binary_path.textChanged.connect(self._emit_changed)
        browse = QPushButton("Choose file…")
        browse.clicked.connect(self._choose_binary)
        row.addWidget(self.binary_path, 1)
        row.addWidget(browse)
        bl.addLayout(row)
        bl.addStretch()
        self.body_stack.addWidget(binary)
        gql = QSplitter(Qt.Orientation.Horizontal)
        self.gql_query = self._code("graphql")
        self.gql_query.setPlaceholderText("query {\n  viewer { id }\n}")
        self.gql_vars = self._code("json")
        self.gql_vars.setPlaceholderText('{\n  "id": 1\n}')
        for w, title in ((self.gql_query, "Query"), (self.gql_vars, "Variables (JSON)")):
            w.textChanged.connect(self._emit_changed)
            box = QWidget()
            bl2 = QVBoxLayout(box)
            bl2.setContentsMargins(0, 0, 4, 0)
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            bl2.addWidget(label)
            bl2.addWidget(w)
            gql.addWidget(box)
        gql.setSizes([600, 300])
        self.body_stack.addWidget(gql)
        lay.addWidget(self.body_stack, 1)
        return page

    def _build_auth(self) -> QWidget:
        self.auth = AuthEditor(variables=self._var_provider)
        self.auth.changed.connect(self._emit_changed)
        return self.auth

    def _build_scripts(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.script_kind = Segmented([("pre", "Pre-request"), ("post", "Post-response")])
        self.script_kind.set_value("pre")
        self.script_kind.changed.connect(self._on_script_kind)
        top.addWidget(self.script_kind)
        top.addStretch()
        self.snippets_btn = QToolButton()
        self.snippets_btn.setText("Snippets ▾")
        self.snippets_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.snippets_menu = QMenu(self.snippets_btn)
        self.snippets_btn.setMenu(self.snippets_menu)
        top.addWidget(self.snippets_btn)
        lay.addLayout(top)
        self.script_stack = QStackedWidget()
        self.pre_script = self._code("python")
        self.pre_script.setPlaceholderText("# runs before the request is sent\n"
                                           "# env['timestamp'] = str(int(time.time()))")
        self.post_script = self._code("python")
        self.post_script.setPlaceholderText("# runs after the response arrives\n"
                                            "# env['token'] = response.json()['access_token']\n"
                                            "# test('status is 200', response.status == 200)")
        for editor in (self.pre_script, self.post_script):
            editor.textChanged.connect(self._emit_changed)
            self.script_stack.addWidget(editor)
        lay.addWidget(self.script_stack, 1)
        help_label = QLabel(SCRIPT_HELP)
        help_label.setObjectName("Dim")
        help_label.setWordWrap(True)
        lay.addWidget(help_label)
        self._on_script_kind("pre")
        return page

    def _build_notes(self) -> QWidget:
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes and documentation for this request…")
        self.notes.textChanged.connect(self._emit_changed)
        return self.notes

    # --- load / dump -------------------------------------------------------------------
    def _load_section(self, name: str, req: dict):
        if name == "params":
            self.params.set_rows(req["params"])
            self.path_vars.set_rows(req["path_vars"])
            self._update_path_visibility()
        elif name == "headers":
            self.headers.set_rows(req["headers"])
        elif name == "body":
            body = req["body"]
            self.body_mode.set_value(body["mode"])
            self.body_text.setPlainText(body["text"])
            self.form.set_rows(body["form"])
            self.urlencoded.set_rows(body["urlencoded"])
            self.binary_path.setText(body["file"])
            self.gql_query.setPlainText(body["graphql"]["query"])
            self.gql_vars.setPlainText(body["graphql"]["variables"])
            self._apply_body_mode(body["mode"])
        elif name == "auth":
            self.auth.set_auth(req["auth"])
            self.auth.set_inherit_hint(self.inherit_hint())
        elif name == "scripts":
            self.pre_script.setPlainText(req["scripts"]["pre"])
            self.post_script.setPlainText(req["scripts"]["post"])
        elif name == "notes":
            self.notes.setPlainText(req.get("description", ""))

    def _dump_section(self, name: str, req: dict):
        if name == "params":
            req["params"] = self.params.rows()
            req["path_vars"] = self.path_vars.rows()
        elif name == "headers":
            req["headers"] = self.headers.rows()
        elif name == "body":
            req["body"] = {"mode": self.body_mode.value(), "text": self.body_text.toPlainText(),
                           "form": self.form.rows(), "urlencoded": self.urlencoded.rows(),
                           "file": self.binary_path.text(),
                           "graphql": {"query": self.gql_query.toPlainText(),
                                       "variables": self.gql_vars.toPlainText()}}
        elif name == "auth":
            req["auth"] = self.auth.auth()
        elif name == "scripts":
            req["scripts"] = {"pre": self.pre_script.toPlainText(), "post": self.post_script.toPlainText()}
        elif name == "notes":
            req["description"] = self.notes.toPlainText()

    def load(self, request: dict):
        self._loading = True
        self._syncing = True
        self._request = copy.deepcopy(request)
        req = self._request
        idx = self.method.findText(req["method"])
        if idx < 0:
            self.method.addItem(req["method"])
            idx = self.method.count() - 1
        self.method.setCurrentIndex(idx)
        self._on_method(req["method"])
        self.url.setText(req["url"])
        self.url.setCursorPosition(0)
        for name in self._built:
            self._load_section(name, req)
        self._syncing = False
        self._loading = False
        self._update_tab_labels()
        self.refresh_highlight()

    def dump(self) -> dict:
        req = copy.deepcopy(self._request)
        req["method"] = self.method.currentText()
        req["url"] = self.url.text()
        for name in self._built:
            self._dump_section(name, req)
        return req

    def set_identity(self, request_id: str, name: str):
        self._request["id"], self._request["name"] = request_id, name

    def refresh_highlight(self):
        self.url.refresh_highlight()
        for table in self._kv_tables:
            table.refresh_highlight()
        for editor in self._code_editors:
            editor.highlighter.rehighlight()
        if "auth" in self._built:
            self.auth.refresh_highlight()
            self.auth.set_inherit_hint(self.inherit_hint())

    def reload_theme(self):
        for editor in self._code_editors:
            editor.reload_theme()
        self._url_sep.setStyleSheet(f"background: {theme.color('border')};")
        if "body" in self._built:
            self.body_error.setStyleSheet(f"color: {theme.color('danger')};")
        self._on_method(self.method.currentText())
        self.refresh_highlight()

    def set_editor_font_size(self, size: int):
        for editor in self._code_editors:
            editor.set_font_size(size)

    # --- state ---------------------------------------------------------------------------
    def set_sending(self, sending: bool):
        self.send_btn.setText("Cancel" if sending else "Send")
        self.send_btn.setToolTip("Cancel request (Esc)" if sending else "Send request (Ctrl+Enter)")
        self.send_btn.setProperty("sending", "true" if sending else "false")
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)

    def focus_url(self):
        self.url.setFocus()
        self.url.selectAll()

    def show_section(self, name: str):
        self.tabs.setCurrentIndex(self.SECTIONS.index(name))

    # --- internal handlers -----------------------------------------------------------------
    def _emit_changed(self, *_):
        if not self._loading:
            self._label_timer.start()
            self.changed.emit()

    def _on_tab_changed(self, index: int):
        self._ensure(self.SECTIONS[index])
        self._update_tab_labels()

    def _on_method(self, method: str):
        self.method.setStyleSheet(f"QComboBox#MethodCombo {{ color: {theme.method_color(method)}; }}")
        for i in range(self.method.count()):
            self.method.setItemData(i, QColor(theme.method_color(self.method.itemText(i))),
                                    Qt.ItemDataRole.ForegroundRole)
        self._emit_changed()

    def _on_url_return(self):
        if not self.url._completer.popup().isVisible():
            self.send_clicked.emit()

    def _handle_paste(self, text: str) -> bool:
        if text.lstrip().startswith(("curl ", "curl\t")):
            self.curl_pasted.emit(text)
            return True
        if "\n" in text.strip():
            self.url.insert(" ".join(text.split()))
            return True
        return False

    def _on_url_changed(self, text: str):
        if self._syncing:
            return
        self._syncing = True
        query_pairs = parse_query(split_url(text)[1])
        disabled = [r for r in self.params.rows() if not r["enabled"]]
        self.params.set_rows([kv(k, v) for k, v in query_pairs] + disabled)
        names = path_variables(text)
        current = {r["key"]: r["value"] for r in self.path_vars.rows()}
        if names != list(current):
            self.path_vars.set_rows([kv(n, current.get(n, "")) for n in names])
        self._update_path_visibility()
        self._syncing = False
        self._emit_changed()

    def _update_path_visibility(self):
        visible = bool(self.path_vars.rows())
        self.path_label.setVisible(visible)
        self.path_vars.setVisible(visible)

    def _on_params_changed(self):
        if self._syncing:
            return
        self._syncing = True
        pairs = [(r["key"], r["value"]) for r in self.params.rows() if r["enabled"] and r["key"]]
        cursor = self.url.cursorPosition()
        self.url.setText(replace_query(self.url.text(), pairs))
        self.url.setCursorPosition(min(cursor, len(self.url.text())))
        self._syncing = False
        self._emit_changed()

    def _on_body_mode(self, mode: str):
        self._apply_body_mode(mode)
        if mode in ("json", "xml", "text") and not self._loading:
            self._ensure_content_type(mode)
        self._emit_changed()

    def _apply_body_mode(self, mode: str):
        index = {"none": 0, "json": 1, "xml": 1, "text": 1, "form": 2, "urlencoded": 3, "binary": 4,
                 "graphql": 5}[mode]
        self.body_stack.setCurrentIndex(index)
        if mode in ("json", "xml", "text"):
            self.body_text.set_language(mode)
        self.beautify_btn.setVisible(mode in ("json", "xml", "graphql"))
        if mode != "json":
            self.body_error.hide()

    def _ensure_content_type(self, mode: str):
        """Keeps an explicit Content-Type header in sync with JSON/XML/Text."""
        wanted = {"json": "application/json", "xml": "application/xml", "text": "text/plain"}[mode]
        rows = self.headers.rows() if "headers" in self._built else self._request["headers"]
        for r in rows:
            if r["key"].lower() == "content-type":
                if r["value"] in ("application/json", "application/xml", "text/plain", "text/xml") \
                        and r["value"] != wanted:
                    r["value"] = wanted
                    if "headers" in self._built:
                        self.headers.set_rows(rows)
                return

    def _on_body_validity(self, ok: bool, message: str):
        self.body_error.setText(message)
        self.body_error.setVisible(not ok and self.body_mode.value() == "json")

    def _choose_binary(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose body file")
        if path:
            self.binary_path.setText(path)

    def _on_script_kind(self, kind: str):
        self.script_stack.setCurrentIndex(0 if kind == "pre" else 1)
        self.snippets_menu.clear()
        editor = self.pre_script if kind == "pre" else self.post_script
        for title, code in (PRE_SNIPPETS if kind == "pre" else POST_SNIPPETS):
            self.snippets_menu.addAction(title, lambda c=code, e=editor: self._insert_snippet(e, c))

    @staticmethod
    def _insert_snippet(editor: CodeEditor, code: str):
        cursor = editor.textCursor()
        if cursor.positionInBlock() > 0:
            code = "\n" + code
        cursor.insertText(code)
        editor.setFocus()

    def beautify(self):
        mode = self.body_mode.value()
        try:
            if mode == "json":
                self.body_text.setPlainText(beautify_json(self.body_text.toPlainText()))
            elif mode == "xml":
                self.body_text.setPlainText(beautify_xml(self.body_text.toPlainText()))
            elif mode == "graphql" and self.gql_vars.toPlainText().strip():
                self.gql_vars.setPlainText(beautify_json(self.gql_vars.toPlainText()))
        except Exception as e:  # noqa: BLE001 - show the parser message to the user
            self.body_error.setText(f"Cannot beautify: {e}")
            self.body_error.show()

    def _update_tab_labels(self):
        req = self.dump()

        def count(rows):
            return sum(1 for r in rows if r.get("enabled", True) and r.get("key"))

        def label(base, n):
            return f"{base} ({n})" if n else base

        self.tabs.setTabText(0, label("Params", count(req["params"])))
        self.tabs.setTabText(1, label("Headers", count(req["headers"])))
        mode = req["body"]["mode"]
        self.tabs.setTabText(2, "Body" if mode == "none" else f"Body · {dict(BODY_MODES)[mode]}")
        self.tabs.setTabText(3, "Auth" if req["auth"]["type"] in ("none", "inherit") else "Auth ●")
        has_script = bool(req["scripts"]["pre"].strip() or req["scripts"]["post"].strip())
        self.tabs.setTabText(4, "Scripts ●" if has_script else "Scripts")
        self.tabs.setTabText(5, "Notes ●" if req.get("description", "").strip() else "Notes")
