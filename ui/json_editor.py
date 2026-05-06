import json
import re
from PySide6.QtWidgets import (QWidget, QPlainTextEdit, QTextEdit)
from PySide6.QtGui import (QPainter, QTextFormat, QColor, QSyntaxHighlighter, 
                           QTextCharFormat, QFont, QShortcut, QKeySequence)
from PySide6.QtCore import Qt, QRect, QSize

class JsonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.formats = {}
        
        # Color palette
        self.formats["key"] = self._format("#ce9178")
        self.formats["string"] = self._format("#9cdcfe")
        self.formats["number"] = self._format("#b5cea8")
        self.formats["bracket"] = self._format("#ffd700")
        self.formats["keyword"] = self._format("#c586c0")

    def _format(self, color, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def highlightBlock(self, text):
        # Very basic JSON highlighting using state-less regex or simple logic
        # For professional use, a state-machine based highlighter is better, 
        # but for this MVP, we'll do basic colorization.
        import re
        
        # Brackets
        for match in re.finditer(r"[\{\}\[\]]", text):
            self.setFormat(match.start(), 1, self.formats["bracket"])
            
        # Strings / Keys
        # Use capturing groups to avoid variable-width look-behind issues
        # Highlight Keys: "key":
        for match in re.finditer(r'("(.*?)")\s*:', text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self.formats["key"])
            
        # Highlight String Values: : "value"
        for match in re.finditer(r':\s*("(.*?)")', text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self.formats["string"])
            
        # Numbers
        for match in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.formats["number"])
            
        # Keywords
        for match in re.finditer(r"\b(true|false|null)\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.formats["keyword"])

class PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = (
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield"
    )
    BUILTINS = (
        "abs", "all", "any", "bin", "bool", "bytes", "callable", "chr",
        "dict", "dir", "divmod", "enumerate", "eval", "exec", "filter",
        "float", "format", "frozenset", "getattr", "globals", "hasattr",
        "hash", "hex", "id", "input", "int", "isinstance", "issubclass",
        "iter", "len", "list", "locals", "map", "max", "min", "next",
        "object", "open", "ord", "pow", "print", "range", "repr",
        "reversed", "round", "set", "setattr", "slice", "sorted", "str",
        "sum", "super", "tuple", "type", "vars", "zip"
    )

    def __init__(self, parent=None):
        super().__init__(parent)

    def _fmt(self, color: str, bold: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def highlightBlock(self, text):
        # Comments
        for m in re.finditer(r"#[^\n]*", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#75715e"))

        # Triple-quoted strings (single-line portion)
        for m in re.finditer(r'""".*?"""|\'\'\'.*?\'\'\'', text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#e6db74"))

        # Single / double quoted strings
        for m in re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#e6db74"))

        # Decorators
        for m in re.finditer(r"@\w+", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#a6e22e"))

        # Keywords
        kw_pat = r"\b(?:" + "|".join(self.KEYWORDS) + r")\b"
        for m in re.finditer(kw_pat, text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#f92672", True))

        # Builtins
        bi_pat = r"\b(?:" + "|".join(self.BUILTINS) + r")\b"
        for m in re.finditer(bi_pat, text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#66d9e8"))

        # Numbers
        for m in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#ae81ff"))

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        
        # Styling
        self.setFont(QFont("Courier New", 11))
        self.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        self.highlighter = JsonHighlighter(self.document())
        
        # Validation
        self.textChanged.connect(self.validate_json)
        
        # Shortcuts
        self.prettify_shortcut = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        self.prettify_shortcut.activated.connect(self.prettify)

    def line_number_area_width(self):
        digits = 1
        max_val = max(1, self.blockCount())
        while max_val >= 10:
            max_val //= 10
            digits += 1
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#2d2d2d"))
        
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#858585"))
                painter.drawText(0, top, self.line_number_area.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        line_color = QColor("#2a2d2e")
        selection.format.setBackground(line_color)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def validate_json(self):
        text = self.toPlainText().strip()
        if not text:
            self.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
            return
            
        try:
            json.loads(text)
            self.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        except ValueError:
            # Light red background on error
            self.setStyleSheet("background-color: #3d1e1e; color: #d4d4d4;")

    def prettify(self):
        text = self.toPlainText().strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
            formatted = json.dumps(parsed, indent=2)
            self.setPlainText(formatted)
        except:
            pass

class PythonCodeEditor(CodeEditor):
    """CodeEditor variant configured for Python pre-request scripts.

    - Replaces JSON highlighter with PythonHighlighter (Monokai palette)
    - Disables JSON validation (no red background flash on syntax errors)
    - Tab key inserts 4 spaces instead of a tab character
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Disconnect JSON-specific validation
        self.textChanged.disconnect(self.validate_json)
        # Swap highlighter to Python
        self.highlighter.setDocument(None)
        self.highlighter = PythonHighlighter(self.document())
        # Neutral Monokai background
        self.setStyleSheet("background-color: #272822; color: #f8f8f2;")
        self.setPlaceholderText(
            "# Pre-request script\n"
            "# Available: env  — dict with current environment variables\n"
            "# Example:\n"
            "# import hashlib\n"
            "# env['signature'] = hashlib.md5(b'secret').hexdigest()"
        )

    def validate_json(self):
        """Intentionally disabled — Python scripts are not JSON."""
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab:
            self.insertPlainText("    ")
        else:
            super().keyPressEvent(event)
