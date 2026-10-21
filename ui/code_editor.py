"""Lightweight code editor: line numbers, regex highlighting (JSON, XML/HTML,
Python, GraphQL) with Monokai colours, ``{{var}}`` highlighting, auto-indent,
bracket pairing and a find bar. No Pygments — highlighting is incremental per
text block and switched off for very large documents."""
import json
import re
from typing import Callable, List, Optional, Set

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QKeySequence, QPainter, QShortcut, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QToolButton, QWidget

from core.variables import VAR_RE
from ui import theme

HIGHLIGHT_LIMIT = 1_500_000  # characters

_JSON_TOKENS = re.compile(r'(?P<string>"(?:[^"\\]|\\.)*"?)(?P<colon>\s*:)?|(?P<number>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
                          r'|(?P<keyword>\b(?:true|false|null)\b)|(?P<punct>[{}\[\],])')
_PY_KEYWORDS = re.compile(r"\b(?:and|as|assert|break|class|continue|def|del|elif|else|except|False|finally|for|"
                          r"from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|"
                          r"while|with|yield)\b")
_PY_STRING = re.compile(r"[rbfu]{0,2}(\"(?:[^\"\\\n]|\\.)*\"?|'(?:[^'\\\n]|\\.)*'?)", re.IGNORECASE)
_PY_BUILTIN = re.compile(r"\b(?:env|variables|request|response|test|log|print|json|re|time|datetime|hashlib|hmac|"
                         r"base64|uuid|random|len|str|int|float|dict|list|range)\b")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_XML_TAG = re.compile(r"</?[\w:.-]+|/?>")
_XML_ATTR = re.compile(r"\b([\w:.-]+)(?==)")
_XML_STRING = re.compile(r"\"[^\"]*\"|'[^']*'")
_GQL_KEYWORDS = re.compile(r"\b(?:query|mutation|subscription|fragment|on|true|false|null)\b")
_GQL_VAR = re.compile(r"\$\w+")
_GQL_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class Highlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, language: str = "text",
                 known_vars: Callable[[], Set[str]] = None):
        super().__init__(document)
        self.language = language
        self.known_vars = known_vars
        self._known_cache: Optional[Set[str]] = None
        self.reload_colors()

    def reload_colors(self):
        s = theme.syntax
        self.f = {k: _fmt(s(k)) for k in ("key", "string", "number", "keyword", "punct", "tag", "attr", "function")}
        self.f["comment"] = _fmt(s("comment"), italic=True)
        self.f["var"] = _fmt(s("variable"), bold=True)
        self.f["var_missing"] = _fmt(s("var_missing"), bold=True)
        self._known_cache = None
        self.rehighlight()

    def set_language(self, language: str):
        if language != self.language:
            self.language = language
            self.rehighlight()

    def rehighlight(self):
        self._known_cache = None
        super().rehighlight()

    def highlightBlock(self, text: str):
        lang = self.language
        if lang == "json":
            self._json(text)
        elif lang == "python":
            self._python(text)
        elif lang in ("xml", "html"):
            self._xml(text)
        elif lang == "graphql":
            self._graphql(text)
        else:
            self.setCurrentBlockState(0)
        if "{{" in text:
            if self._known_cache is None:
                self._known_cache = self.known_vars() if self.known_vars else set()
            for m in VAR_RE.finditer(text):
                name = m.group(1)
                ok = name in self._known_cache or name.startswith("$")
                self.setFormat(m.start(), m.end() - m.start(), self.f["var"] if ok else self.f["var_missing"])

    def _json(self, text):
        for m in _JSON_TOKENS.finditer(text):
            if m.group("string") is not None:
                kind = "key" if m.group("colon") else "string"
                self.setFormat(m.start("string"), len(m.group("string")), self.f[kind])
            elif m.group("number") is not None:
                self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
            elif m.group("keyword") is not None:
                self.setFormat(m.start(), m.end() - m.start(), self.f["keyword"])
            else:
                self.setFormat(m.start(), 1, self.f["punct"])

    def _python(self, text):
        for m in _NUMBER.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
        for m in _PY_BUILTIN.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["function"])
        for m in _PY_KEYWORDS.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["key"])
        strings = []
        for m in _PY_STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["string"])
            strings.append((m.start(), m.end()))
        hash_pos = text.find("#")
        while hash_pos >= 0:
            if not any(a <= hash_pos < b for a, b in strings):
                self.setFormat(hash_pos, len(text) - hash_pos, self.f["comment"])
                break
            hash_pos = text.find("#", hash_pos + 1)
        # triple-quoted strings spanning blocks
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() == 1:
            end = text.find('"""')
            if end < 0:
                self.setFormat(0, len(text), self.f["string"])
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 3, self.f["string"])
            start = end + 3
        while True:
            begin = text.find('"""', start)
            if begin < 0:
                break
            end = text.find('"""', begin + 3)
            if end < 0:
                self.setFormat(begin, len(text) - begin, self.f["string"])
                self.setCurrentBlockState(1)
                break
            self.setFormat(begin, end + 3 - begin, self.f["string"])
            start = end + 3

    def _xml(self, text):
        for m in _XML_TAG.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["tag"])
        for m in _XML_ATTR.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["attr"])
        for m in _XML_STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["string"])
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() == 1:
            end = text.find("-->")
            if end < 0:
                self.setFormat(0, len(text), self.f["comment"])
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 3, self.f["comment"])
            start = end + 3
        while True:
            begin = text.find("<!--", start)
            if begin < 0:
                break
            end = text.find("-->", begin + 4)
            if end < 0:
                self.setFormat(begin, len(text) - begin, self.f["comment"])
                self.setCurrentBlockState(1)
                break
            self.setFormat(begin, end + 3 - begin, self.f["comment"])
            start = end + 3

    def _graphql(self, text):
        for m in _GQL_KEYWORDS.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["key"])
        for m in _GQL_VAR.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
        for m in _GQL_STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["string"])
        pos = text.find("#")
        if pos >= 0:
            self.setFormat(pos, len(text) - pos, self.f["comment"])


class _LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


_PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"'}


class CodeEditor(QPlainTextEdit):
    validity_changed = Signal(bool, str)

    def __init__(self, language: str = "text", read_only: bool = False, parent=None,
                 known_vars: Callable[[], Set[str]] = None, line_numbers: bool = True):
        super().__init__(parent)
        self.setObjectName("CodeEditor")
        self.language = language
        self._line_numbers = line_numbers
        self.setReadOnly(read_only)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(theme.mono_font())
        self.highlighter = Highlighter(self.document(), language, known_vars)
        self._gutter = _LineNumbers(self) if line_numbers else None
        if read_only:
            self.setUndoRedoEnabled(False)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._update_gutter_width()
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(400)
        self._validate_timer.timeout.connect(self.validate)
        self.textChanged.connect(self._on_text_changed)
        self._search_selections: List[QTextEdit.ExtraSelection] = []

    # --- language / content --------------------------------------------------
    def set_language(self, language: str):
        self.language = language
        if self.highlighter.document() is not None:
            self.highlighter.set_language(language)
        self.validate()

    def set_font_size(self, size: int):
        self.setFont(theme.mono_font(size))
        self._update_gutter_width()

    def setPlainText(self, text: str):
        big = len(text) > HIGHLIGHT_LIMIT
        if big and self.highlighter.document() is not None:
            self.highlighter.setDocument(None)
        super().setPlainText(text)
        if not big and self.highlighter.document() is None:
            self.highlighter.setDocument(self.document())

    def reload_theme(self):
        self.highlighter.reload_colors()
        self._highlight_line()

    def _on_text_changed(self):
        if not self.isReadOnly() and self.language == "json":
            self._validate_timer.start()

    def validate(self):
        if self.language != "json" or self.isReadOnly():
            self._set_error(False, "")
            return
        text = self.toPlainText().strip()
        if not text:
            self._set_error(False, "")
            return
        probe = VAR_RE.sub("0", text)  # {{vars}} are valid placeholders
        try:
            json.loads(probe)
            self._set_error(False, "")
        except ValueError as e:
            self._set_error(True, f"Invalid JSON: {e}")

    def _set_error(self, error: bool, message: str):
        if bool(self.property("error") == "true") != error:
            self.setProperty("error", "true" if error else "false")
            self.style().unpolish(self)
            self.style().polish(self)
        self.validity_changed.emit(not error, message)

    # --- gutter ----------------------------------------------------------------
    def gutter_width(self) -> int:
        if not self._line_numbers:
            return 0
        digits = max(3, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if not self._gutter:
            return
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._gutter:
            cr = self.contentsRect()
            self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(theme.color("surface") if self.isReadOnly() else theme.color("surface2")))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        dim, bright = QColor(theme.color("text_faint")), QColor(theme.color("text_dim"))
        width = self._gutter.width() - 6
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(bright if number == current else dim)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def _highlight_line(self):
        extra = list(self._search_selections)
        if not self.isReadOnly() and self.hasFocus():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(theme.color("surface3")))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.insert(0, sel)
        self.setExtraSelections(extra)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._highlight_line()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._highlight_line()

    # --- editing helpers ---------------------------------------------------------
    def keyPressEvent(self, e):
        if self.isReadOnly():
            super().keyPressEvent(e)
            return
        key, mods, text = e.key(), e.modifiers(), e.text()
        cursor = self.textCursor()
        indent = "    " if self.language == "python" else "  "
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not mods & Qt.KeyboardModifier.ControlModifier:
            line = cursor.block().text()[:cursor.positionInBlock()]
            lead = line[:len(line) - len(line.lstrip())]
            stripped = line.rstrip()
            after = cursor.block().text()[cursor.positionInBlock():].lstrip()
            if stripped.endswith(("{", "[", "(", ":")) and not (self.language != "python" and stripped.endswith(":")):
                if after[:1] in ("}", "]", ")") and stripped[-1] in "{[(":
                    cursor.insertText("\n" + lead + indent + "\n" + lead)
                    cursor.movePosition(QTextCursor.MoveOperation.Up)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    self.setTextCursor(cursor)
                    return
                lead += indent
            cursor.insertText("\n" + lead)
            self.ensureCursorVisible()
            return
        if key == Qt.Key.Key_Tab and not cursor.hasSelection():
            cursor.insertText(indent)
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._indent_selection(indent, dedent=key == Qt.Key.Key_Backtab)
            return
        if key == Qt.Key.Key_Slash and mods & Qt.KeyboardModifier.ControlModifier and self.language == "python":
            self._toggle_comment()
            return
        if text in _PAIRS and self.language in ("json", "python", "graphql", "text"):
            closing = _PAIRS[text]
            if cursor.hasSelection():
                selected = cursor.selectedText()
                cursor.insertText(text + selected + closing)
                return
            nxt = self.document().characterAt(cursor.position())
            if text == '"' and nxt == '"':
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return
            if not nxt.strip() or nxt in ")]},:":
                cursor.insertText(text + closing)
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.setTextCursor(cursor)
                return
        if text in (")", "]", "}") and self.document().characterAt(cursor.position()) == text:
            cursor.movePosition(QTextCursor.MoveOperation.Right)
            self.setTextCursor(cursor)
            return
        if key == Qt.Key.Key_Backspace and not cursor.hasSelection():
            prev = self.document().characterAt(cursor.position() - 1)
            nxt = self.document().characterAt(cursor.position())
            if prev in _PAIRS and _PAIRS[prev] == nxt:
                cursor.deleteChar()
        super().keyPressEvent(e)

    def _indent_selection(self, indent: str, dedent: bool):
        cursor = self.textCursor()
        doc = self.document()
        start = doc.findBlock(cursor.selectionStart())
        end = doc.findBlock(cursor.selectionEnd())
        cursor.beginEditBlock()
        block = start
        while True:
            c = QTextCursor(block)
            if dedent:
                txt = block.text()
                n = len(txt) - len(txt.lstrip(" "))
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, min(n, len(indent)))
                c.removeSelectedText()
            else:
                c.insertText(indent)
            if block == end:
                break
            block = block.next()
        cursor.endEditBlock()

    def _toggle_comment(self):
        cursor = self.textCursor()
        doc = self.document()
        start, end = doc.findBlock(cursor.selectionStart()), doc.findBlock(cursor.selectionEnd())
        blocks = []
        block = start
        while True:
            blocks.append(block)
            if block == end:
                break
            block = block.next()
        commented = all(b.text().lstrip().startswith("#") or not b.text().strip() for b in blocks)
        cursor.beginEditBlock()
        for b in blocks:
            text = b.text()
            if not text.strip():
                continue
            c = QTextCursor(b)
            lead = len(text) - len(text.lstrip())
            c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, lead)
            if commented:
                n = 2 if text.lstrip().startswith("# ") else 1
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, n)
                c.removeSelectedText()
            else:
                c.insertText("# ")
        cursor.endEditBlock()

    # --- search ------------------------------------------------------------------
    def find_all(self, needle: str, case: bool = False) -> int:
        self._search_selections = []
        if needle:
            flags = QTextDocument.FindFlag.FindCaseSensitively if case else QTextDocument.FindFlag(0)
            fmt_bg = QColor(theme.color("warning"))
            fmt_bg.setAlpha(90)
            cursor = self.document().find(needle, 0, flags)
            while not cursor.isNull() and len(self._search_selections) < 2000:
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(fmt_bg)
                sel.cursor = cursor
                self._search_selections.append(sel)
                cursor = self.document().find(needle, cursor, flags)
        self._highlight_line()
        return len(self._search_selections)

    def find_next(self, needle: str, backward: bool = False, case: bool = False) -> bool:
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if case:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.find(needle, flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return self.find(needle, flags)


class FindBar(QWidget):
    """Ctrl+F search strip for a CodeEditor."""

    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find")
        self.edit.setClearButtonEnabled(True)
        self.count = QLabel("")
        self.count.setObjectName("Dim")
        prev_btn, next_btn, close_btn = QToolButton(), QToolButton(), QToolButton()
        prev_btn.setText("↑")
        next_btn.setText("↓")
        close_btn.setText("✕")
        prev_btn.setToolTip("Previous (Shift+Enter)")
        next_btn.setToolTip("Next (Enter)")
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.count)
        lay.addWidget(prev_btn)
        lay.addWidget(next_btn)
        lay.addWidget(close_btn)
        self.edit.textChanged.connect(self._on_text)
        self.edit.returnPressed.connect(lambda: self.editor.find_next(self.edit.text()))
        prev_btn.clicked.connect(lambda: self.editor.find_next(self.edit.text(), backward=True))
        next_btn.clicked.connect(lambda: self.editor.find_next(self.edit.text()))
        close_btn.clicked.connect(self.close_bar)
        for keys, slot in (("Escape", self.close_bar),
                           ("Shift+Return", lambda: self.editor.find_next(self.edit.text(), backward=True))):
            shortcut = QShortcut(QKeySequence(keys), self.edit, slot)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.hide()

    def open_bar(self):
        self.show()
        selected = self.editor.textCursor().selectedText()
        if selected and " " not in selected:
            self.edit.setText(selected)
        self.edit.setFocus()
        self.edit.selectAll()
        self._on_text(self.edit.text())

    def close_bar(self):
        self.editor.find_all("")
        self.hide()
        self.editor.setFocus()

    def _on_text(self, text):
        n = self.editor.find_all(text)
        self.count.setText(f"{n} match{'es' if n != 1 else ''}" if text else "")
        if text:
            cursor = self.editor.textCursor()
            cursor.setPosition(cursor.selectionStart())
            self.editor.setTextCursor(cursor)
            self.editor.find_next(text)
