"""Line edit with ``{{variable}}`` highlighting, hover tooltips and an
autocomplete popup (variables after ``{{``, otherwise context suggestions
such as URLs from history or header names)."""
import re
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QInputMethodEvent, QKeySequence, QPainter,
                           QStandardItem, QStandardItemModel, QTextCharFormat)
from PySide6.QtWidgets import QCompleter, QLineEdit, QStyle, QStyledItemDelegate, QToolTip

from core.completion import rank
from core.variables import find_vars
from ui import theme

VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
_VAR_TAIL = re.compile(r"[^{}\s]*\}\}")

# provider() -> [(name, value, source)]
VarProvider = Callable[[], List[Tuple[str, str, str]]]


class _PopupDelegate(QStyledItemDelegate):
    """Name on the left, dimmed value/hint on the right."""

    def paint(self, painter: QPainter, option, index):
        self.initStyleOption(option, index)
        hint = index.data(VALUE_ROLE) or ""
        text = option.text
        option.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        rect = option.rect.adjusted(8, 0, -8, 0)
        painter.save()
        painter.setFont(option.font)
        fm = painter.fontMetrics()
        name_w = min(fm.horizontalAdvance(text) + 4, int(rect.width() * (0.6 if hint else 1.0)))
        painter.setPen(QColor(theme.color("text")))
        painter.drawText(QRect(rect.left(), rect.top(), name_w, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(text, Qt.TextElideMode.ElideMiddle, name_w))
        if hint:
            painter.setPen(QColor(theme.color("text_dim")))
            hint_rect = QRect(rect.left() + name_w + 16, rect.top(), rect.width() - name_w - 16, rect.height())
            painter.drawText(hint_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             fm.elidedText(hint.replace("\n", " "), Qt.TextElideMode.ElideRight, hint_rect.width()))
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 26))


class SmartLineEdit(QLineEdit):
    """``suggest(text) -> [str]`` gives context completions; ``variables()``
    lists known variables for ``{{`` completion and highlighting."""

    pasted_text = Signal(str)

    def __init__(self, parent=None, suggest: Callable[[str], List[str]] = None,
                 variables: Optional[VarProvider] = None, paste_handler: Callable[[str], bool] = None):
        super().__init__(parent)
        self._suggest = suggest
        self._variables = variables
        self._paste_handler = paste_handler
        self._mode = None
        self._var_start = 0
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(10)
        self._completer.popup().setItemDelegate(_PopupDelegate(self._completer.popup()))
        self._completer.popup().setObjectName("CompleterPopup")
        self._completer.activated[str].connect(self._on_activated)
        self.setMouseTracking(True)
        self.textEdited.connect(self._on_edited)
        self.textChanged.connect(self._schedule_highlight)
        self._hl_timer = QTimer(self)
        self._hl_timer.setSingleShot(True)
        self._hl_timer.setInterval(0)
        self._hl_timer.timeout.connect(self.refresh_highlight)

    def set_suggest(self, suggest):
        self._suggest = suggest

    def set_variables(self, provider: Optional[VarProvider]):
        self._variables = provider
        self._schedule_highlight()

    # --- highlighting -----------------------------------------------------------
    def _schedule_highlight(self):
        self._hl_timer.start()

    def refresh_highlight(self):
        spans = find_vars(self.text())
        known = None
        if spans and self._variables:
            known = {name for name, _v, _s in self._variables()}
        attrs = []
        cursor = self.cursorPosition()
        for start, end, name in spans:
            fmt = QTextCharFormat()
            ok = known is not None and (name in known or name.startswith("$"))
            fmt.setForeground(QColor(theme.syntax("variable") if ok else theme.syntax("var_missing")))
            fmt.setFontWeight(QFont.Weight.DemiBold)
            attrs.append(QInputMethodEvent.Attribute(QInputMethodEvent.AttributeType.TextFormat,
                                                     start - cursor, end - start, fmt))
        if attrs or getattr(self, "_had_formats", False):
            QCoreApplication.sendEvent(self, QInputMethodEvent("", attrs))
        self._had_formats = bool(attrs)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            pos = self.cursorPositionAt(e.pos())
            for start, end, name in find_vars(self.text()):
                if start <= pos <= end:
                    QToolTip.showText(e.globalPos(), self._describe_var(name), self)
                    return True
            QToolTip.hideText()
            return True
        return super().event(e)

    def _describe_var(self, name: str) -> str:
        for var, value, source in (self._variables() if self._variables else []):
            if var == name:
                if source == "dynamic":
                    return f"{{{{{name}}}}} — dynamic, generated on send"
                shown = value if len(value) < 300 else value[:300] + "…"
                return f"{{{{{name}}}}} = {shown}\nfrom {source}"
        return f"{{{{{name}}}}} is not defined in the active environment"

    # --- completion ---------------------------------------------------------------
    def _on_edited(self, _text):
        self.update_completions()

    def update_completions(self, force: bool = False):
        text, pos = self.text(), self.cursorPosition()
        before = text[:pos]
        open_at = before.rfind("{{")
        items: List[Tuple[str, str]] = []
        if open_at >= 0 and "}}" not in before[open_at:] and self._variables:
            prefix = before[open_at + 2:].strip()
            variables = self._variables()
            if not prefix.startswith("$"):  # dynamic {{$guid}}-style variables only on request
                variables = [v for v in variables if v[2] != "dynamic"]
            values = {n: (v if s != "dynamic" else "dynamic") for n, v, s in variables}
            items = [(n, values[n]) for n in rank(prefix, [n for n, _, _ in variables], limit=30)]
            self._mode, self._var_start = "var", open_at
        elif self._suggest and (text or force):
            items = [(s, "") for s in self._suggest(text) if s != text]
            self._mode = "full"
        self._model.clear()
        for name, hint in items:
            it = QStandardItem(name)
            it.setData(hint, VALUE_ROLE)
            self._model.appendRow(it)
        if not items:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._model.index(0, 0) if self._mode == "var" else popup.rootIndex())
        rect = self.rect()
        rect.setWidth(max(self.width(), 360))
        self._completer.complete(rect)

    def _on_activated(self, value: str):
        if self._mode == "var":
            text, pos = self.text(), self.cursorPosition()
            # editing inside an existing {{var}}: replace through its closing braces
            m = _VAR_TAIL.match(text, pos)
            end = m.end() if m else pos
            new = text[:self._var_start] + "{{" + value + "}}" + text[end:]
            self.setText(new)
            self.setCursorPosition(self._var_start + len(value) + 4)
        else:
            self.setText(value)
        self.textEdited.emit(self.text())
        self._completer.popup().hide()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Paste) and self._paste_handler:
            text = QGuiApplication.clipboard().text()
            if text and self._paste_handler(text):
                return
        if e.key() == Qt.Key.Key_Space and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.update_completions(force=True)
            return
        super().keyPressEvent(e)
        if e.text() == "{" and self.text()[:self.cursorPosition()].endswith("{{"):
            self.update_completions()

    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu()
        if self._paste_handler:
            for action in menu.actions():
                if action.objectName() == "edit-paste":
                    action.triggered.disconnect()
                    action.triggered.connect(self._paste_from_menu)
        menu.exec(e.globalPos())
        menu.deleteLater()

    def _paste_from_menu(self):
        text = QGuiApplication.clipboard().text()
        if text and self._paste_handler and self._paste_handler(text):
            return
        self.paste()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.refresh_highlight()
