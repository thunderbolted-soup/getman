"""Response panel: status line, Body (pretty/raw/image preview, find), Headers,
Cookies and Console (timeline of what was actually sent + script output)."""
import json
from typing import List, Optional

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from core.http_client import ResponseData
from ui import theme
from ui.code_editor import CodeEditor, FindBar
from ui.icons import set_icon
from ui.request_editor import Segmented

PRETTY_LIMIT = 5 * 1024 * 1024
DISPLAY_LIMIT = 20 * 1024 * 1024


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def _charset(resp: ResponseData) -> str:
    header = resp.header("Content-Type") or ""
    for part in header.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset" and v:
            return v.strip('"')
    return "utf-8"


def decode_body(resp: ResponseData) -> str:
    if "text" not in resp.cache:
        body = resp.body[:DISPLAY_LIMIT]
        try:
            text = body.decode(_charset(resp), errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        if len(resp.body) > DISPLAY_LIMIT:
            text += f"\n\n… truncated: showing {human_size(DISPLAY_LIMIT)} of {human_size(len(resp.body))}. " \
                    "Use Save to get the full body."
        resp.cache["text"] = text
    return resp.cache["text"]


def detect_language(resp: ResponseData, text: str) -> str:
    ct = resp.content_type
    head = text.lstrip()[:1]
    if "json" in ct or (head in ("{", "[") and "html" not in ct):
        return "json"
    if "xml" in ct or "html" in ct or head == "<":
        return "xml"
    return "text"


def pretty_body(resp: ResponseData) -> tuple:
    """(text, language) — JSON is re-indented, XML pretty printed when small."""
    if "pretty" in resp.cache:
        return resp.cache["pretty"]
    text = decode_body(resp)
    lang = detect_language(resp, text)
    pretty = text
    if len(resp.body) <= PRETTY_LIMIT:
        if lang == "json":
            try:
                pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        elif lang == "xml" and "html" not in resp.content_type and text.lstrip().startswith("<"):
            try:
                from ui.request_editor import beautify_xml
                pretty = beautify_xml(text)
            except Exception:  # noqa: BLE001 - malformed XML is shown as-is
                pass
    result = (pretty, lang)
    if len(pretty) < 2_000_000:
        resp.cache["pretty"] = result
    return result


def parse_cookies(resp: ResponseData) -> List[dict]:
    cookies = []
    for k, v in resp.headers:
        if k.lower() != "set-cookie":
            continue
        for line in v.split("\n"):
            parts = [p.strip() for p in line.split(";")]
            if not parts or "=" not in parts[0]:
                continue
            name, _, value = parts[0].partition("=")
            attrs = {"domain": "", "path": "", "expires": "", "flags": []}
            for p in parts[1:]:
                key, _, val = p.partition("=")
                key_l = key.lower()
                if key_l in ("domain", "path", "expires"):
                    attrs[key_l] = val
                elif key_l == "max-age":
                    attrs["expires"] = attrs["expires"] or f"max-age={val}"
                elif key:
                    attrs["flags"].append(key if not val else f"{key}={val}")
            cookies.append({"name": name, "value": value, **attrs, "flags": ", ".join(attrs["flags"])})
    return cookies


def format_console(prep, resp: Optional[ResponseData] = None, error: str = None, post_script=None) -> str:
    lines = []
    if prep is not None:
        lines.append(f"> {prep.method} {prep.url}")
        for k, v in prep.headers:
            lines.append(f"  {k}: {v}")
        if prep.multipart is not None:
            lines.append("")
            for part in prep.multipart:
                lines.append(f"  [form] {part['name']} = " + (f"@{part['file']}" if "file" in part else part["value"]))
        elif prep.body_file:
            lines.append(f"\n  [file] {prep.body_file}")
        elif prep.body:
            body = prep.body[:4000].decode("utf-8", errors="replace")
            lines.append("")
            lines.extend("  " + ln for ln in body.splitlines())
            if len(prep.body) > 4000:
                lines.append(f"  … ({human_size(len(prep.body))} total)")
        for w in prep.warnings:
            lines.append(f"! {w}")
        if prep.script is not None:
            lines.extend(_script_lines("pre-request", prep.script))
    if resp is not None:
        lines.append("")
        lines.append(f"< {resp.http_version} {resp.status} {resp.reason}   ·  {resp.elapsed_ms} ms "
                     f"(first byte {resp.ttfb_ms} ms)  ·  {human_size(resp.size)}")
        if resp.url and prep is not None and resp.url != prep.url:
            lines.append(f"  final URL after redirects: {resp.url}")
        for k, v in resp.headers:
            lines.append(f"  {k}: {v}")
    if error:
        lines.append("")
        lines.append(f"x {error}")
    if post_script is not None:
        lines.extend(_script_lines("post-response", post_script))
    return "\n".join(lines)


def _script_lines(label: str, result) -> List[str]:
    out = []
    if result.logs or result.error or result.tests or result.env_changes:
        out.append("")
        out.append(f"— {label} script —")
    out.extend(f"  {line}" for line in result.logs)
    for name, passed, msg in result.tests:
        out.append(f"  {'[pass]' if passed else '[FAIL]'} {name}" + (f" — {msg}" if msg else ""))
    for k, v in result.env_changes.items():
        shown = v if len(v) < 80 else v[:77] + "…"
        out.append(f"  env[{k!r}] = {shown!r}")
    if result.error:
        out.append(f"  x {result.error}")
    return out


class ResponseView(QWidget):
    """Pages and tabs are created on first use to keep idle memory low."""
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resp: Optional[ResponseData] = None
        self._console = ""
        self._tests: list = []
        self._mode = "pretty"
        self._font_size = 10
        self._pages = {}
        self._rendered = set()
        self.find_bar = None
        self.image = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self._clock = QElapsedTimer()
        self._offset = 0
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)
        self.show_empty()

    # --- lazy pages ------------------------------------------------------------------------
    def _page(self, name: str) -> QWidget:
        if name not in self._pages:
            page = getattr(self, f"_build_{name}")()
            self._pages[name] = page
            self.stack.addWidget(page)
        return self._pages[name]

    @staticmethod
    def _centered(*widgets) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch()
        for w in widgets:
            if isinstance(w, QWidget):
                lay.addWidget(w)
            else:
                lay.addLayout(w)
        lay.addStretch()
        return page

    def _build_empty(self) -> QWidget:
        title = QLabel("Send a request to see the response")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hints = QLabel("Ctrl+Enter  send   ·   Ctrl+T  new tab   ·   Ctrl+P  find request   ·   Ctrl+I  import")
        hints.setObjectName("Faint")
        hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return self._centered(title, hints)

    def _build_loading(self) -> QWidget:
        self.loading_label = QLabel("Sending request…")
        self.loading_label.setObjectName("Title")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel_clicked)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addStretch()
        return self._centered(self.loading_label, row)

    def _build_error(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 12)
        self.error_title = QLabel()
        self.error_title.setObjectName("Title")
        self.error_title.setStyleSheet(f"color: {theme.color('danger')};")
        self.error_text = QLabel()
        self.error_text.setWordWrap(True)
        self.error_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_console = QPlainTextEdit()
        self.error_console.setObjectName("Console")
        self.error_console.setReadOnly(True)
        self.error_console.setFont(theme.mono_font(self._font_size))
        lay.addWidget(self.error_title)
        lay.addWidget(self.error_text)
        lay.addWidget(self.error_console, 1)
        return page

    def _build_response(self) -> QWidget:
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        head = QWidget()
        head.setObjectName("Card")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 6, 10, 0)
        hl.setSpacing(12)
        self.status = QLabel()
        self.time_label = QLabel()
        self.time_label.setObjectName("Dim")
        self.size_label = QLabel()
        self.size_label.setObjectName("Dim")
        self.tests_label = QLabel()
        self.tests_label.hide()
        for w in (self.status, self.time_label, self.size_label, self.tests_label):
            hl.addWidget(w)
        hl.addStretch()
        self.view_mode = Segmented([("pretty", "Pretty"), ("raw", "Raw"), ("preview", "Preview")])
        self.view_mode.set_value("pretty")
        self.view_mode.changed.connect(self._on_view_mode)
        hl.addWidget(self.view_mode)
        wrap = self._tool("wrap", "Wrap lines", checkable=True)
        wrap.toggled.connect(self._on_wrap)
        for button, slot in ((wrap, None), (self._tool("search", "Find (Ctrl+F)"), self.open_find),
                             (self._tool("copy", "Copy body"), self._copy),
                             (self._tool("download", "Save body to file"), self._save)):
            if slot:
                button.clicked.connect(slot)
            hl.addWidget(button)
        pl.addWidget(head)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        body_page = QWidget()
        self.body_layout = QVBoxLayout(body_page)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.body_stack = QStackedWidget()
        self.body = CodeEditor("json", read_only=True)
        self.body.setObjectName("ResponseBody")
        self.body.set_font_size(self._font_size)
        self.body_stack.addWidget(self.body)
        self.body_layout.addWidget(self.body_stack)
        self.tabs.addTab(body_page, "Body")
        self._tab_holders = {}
        for name in ("headers", "cookies", "console"):
            holder = QWidget()
            QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
            self._tab_holders[name] = holder
            self.tabs.addTab(holder, name.capitalize())
        self.tabs.currentChanged.connect(self._render_tab)
        pl.addWidget(self.tabs, 1)
        return page

    @staticmethod
    def _tool(icon_name: str, tip: str, checkable: bool = False) -> QToolButton:
        b = QToolButton()
        set_icon(b, icon_name)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    @staticmethod
    def _table(headers) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().hide()
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setWordWrap(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setDefaultSectionSize(28)
        return t

    # --- states -------------------------------------------------------------------------------
    def show_empty(self):
        self._tick.stop()
        self._resp = None
        self.stack.setCurrentWidget(self._page("empty"))

    def show_loading(self, started_ms_ago: int = 0):
        page = self._page("loading")
        self._clock.start()
        self._offset = started_ms_ago
        self._on_tick()
        self._tick.start()
        self.stack.setCurrentWidget(page)

    def _on_tick(self):
        seconds = (self._clock.elapsed() + self._offset) / 1000
        self.loading_label.setText(f"Sending request…  {seconds:.1f} s")

    def show_error(self, message: str, console: str = ""):
        page = self._page("error")
        self._tick.stop()
        self._resp = None
        cancelled = message == "cancelled"
        self.error_title.setText("Request cancelled" if cancelled else "Could not get a response")
        self.error_text.setText("The request was cancelled." if cancelled else message)
        self.error_console.setPlainText(console)
        self.error_console.setVisible(bool(console))
        self.stack.setCurrentWidget(page)

    def show_response(self, resp: ResponseData, console: str = "", tests=None):
        page = self._page("response")
        self._tick.stop()
        self._resp, self._console, self._tests = resp, console, tests or []
        self._rendered = set()
        color = theme.status_color(resp.status)
        self.status.setText(f"{resp.status} {resp.reason}".strip())
        self.status.setStyleSheet(f"color: {color}; font-weight: 700; padding: 3px 8px; border-radius: 5px;"
                                  f"background: {theme.rgba(color, 0.14)};")
        self.time_label.setText(f"{resp.elapsed_ms} ms")
        self.time_label.setToolTip(f"First byte after {resp.ttfb_ms} ms · {resp.http_version}")
        self.size_label.setText(human_size(resp.size))
        if self._tests:
            passed = sum(1 for t in self._tests if t[1])
            ok = passed == len(self._tests)
            self.tests_label.setText(f"Tests {passed}/{len(self._tests)}")
            self.tests_label.setStyleSheet(f"color: {theme.color('success' if ok else 'danger')}; font-weight: 600;")
        self.tests_label.setVisible(bool(self._tests))
        is_image = resp.content_type.startswith("image/")
        self.view_mode.buttons["preview"].setVisible(is_image)
        mode = self._mode if (self._mode != "preview" or is_image) else "pretty"
        if is_image and self._mode == "pretty":
            mode = "preview"
        self.view_mode.set_value(mode)
        self._render_body(mode)
        n_cookies = len(parse_cookies(resp))
        self.tabs.setTabText(1, f"Headers ({len(resp.headers)})")
        self.tabs.setTabText(2, f"Cookies ({n_cookies})" if n_cookies else "Cookies")
        failed = any(not t[1] for t in self._tests)
        self.tabs.setTabText(3, "Console ●" if failed else "Console")
        self._render_tab(self.tabs.currentIndex())
        self.stack.setCurrentWidget(page)

    def _render_tab(self, index: int):
        """Headers / Cookies / Console are filled only when looked at."""
        name = {1: "headers", 2: "cookies", 3: "console"}.get(index)
        if name is None or self._resp is None or name in self._rendered:
            return
        self._rendered.add(name)
        holder = self._tab_holders[name]
        if name == "headers":
            if not hasattr(self, "headers_table"):
                self.headers_table = self._table(["Header", "Value"])
                holder.layout().addWidget(self.headers_table)
            self.headers_table.setRowCount(len(self._resp.headers))
            for i, (k, v) in enumerate(self._resp.headers):
                self.headers_table.setItem(i, 0, QTableWidgetItem(k))
                self.headers_table.setItem(i, 1, QTableWidgetItem(v))
        elif name == "cookies":
            if not hasattr(self, "cookies_table"):
                self.cookies_table = self._table(["Name", "Value", "Domain", "Path", "Expires", "Flags"])
                holder.layout().addWidget(self.cookies_table)
            cookies = parse_cookies(self._resp)
            self.cookies_table.setRowCount(len(cookies))
            for i, c in enumerate(cookies):
                for j, key in enumerate(("name", "value", "domain", "path", "expires", "flags")):
                    self.cookies_table.setItem(i, j, QTableWidgetItem(c[key]))
        else:
            if not hasattr(self, "console"):
                self.console = QPlainTextEdit()
                self.console.setObjectName("Console")
                self.console.setReadOnly(True)
                self.console.setFont(theme.mono_font(self._font_size))
                self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                holder.layout().addWidget(self.console)
            self.console.setPlainText(self._console)

    def _render_body(self, mode: str):
        resp = self._resp
        if resp is None:
            return
        if mode == "preview":
            pix = QPixmap()
            if resp.size < DISPLAY_LIMIT and pix.loadFromData(resp.body):
                if self.image is None:
                    self.image = QLabel()
                    self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setWidget(self.image)
                    self.body_stack.addWidget(scroll)
                self.image.setPixmap(pix)
                self.body_stack.setCurrentIndex(1)
                return
            mode = "raw"
        if self.image is not None:
            self.image.clear()
        self.body_stack.setCurrentIndex(0)
        if mode == "pretty":
            text, lang = pretty_body(resp)
        else:
            text = decode_body(resp)
            lang = detect_language(resp, text) if len(text) < 300_000 else "text"
        self.body.set_language(lang)
        self.body.setPlainText(text)
        if self.find_bar is not None and self.find_bar.isVisible() and self.find_bar.edit.text():
            self.body.find_all(self.find_bar.edit.text())

    def _on_view_mode(self, mode: str):
        self._mode = mode
        self._render_body(mode)

    def _on_wrap(self, on: bool):
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if on else
                                  QPlainTextEdit.LineWrapMode.NoWrap)

    def open_find(self):
        if self._resp is None or self.stack.currentWidget() is not self._pages.get("response"):
            return
        if self.find_bar is None:
            self.find_bar = FindBar(self.body)
            self.body_layout.insertWidget(0, self.find_bar)
        self.tabs.setCurrentIndex(0)
        self.find_bar.open_bar()

    def _copy(self):
        if self._resp is not None:
            QGuiApplication.clipboard().setText(self.body.toPlainText())

    def _save(self):
        if self._resp is None:
            return
        ext = {"json": ".json", "xml": ".xml"}.get(detect_language(self._resp, ""), "")
        if self._resp.content_type.startswith("image/"):
            ext = "." + self._resp.content_type.split("/", 1)[1].split("+")[0]
        path, _ = QFileDialog.getSaveFileName(self, "Save response body", "response" + ext)
        if path:
            with open(path, "wb") as f:
                f.write(self._resp.body)

    def reload_theme(self):
        if "response" in self._pages:
            self.body.reload_theme()
        if "error" in self._pages:
            self.error_title.setStyleSheet(f"color: {theme.color('danger')};")

    def set_editor_font_size(self, size: int):
        self._font_size = size
        if "response" in self._pages:
            self.body.set_font_size(size)
        if hasattr(self, "console"):
            self.console.setFont(theme.mono_font(size))
        if "error" in self._pages:
            self.error_console.setFont(theme.mono_font(size))
