"""Ctrl+P quick-open palette: saved requests, recent history, environments and
app actions, with ranked fuzzy-ish matching."""
from typing import Callable, List, Tuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QDialog, QFrame, QLineEdit, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout)

from core.models import iter_requests
from ui import theme

DATA = Qt.ItemDataRole.UserRole


class _Delegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        entry = index.data(DATA)
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        rect = option.rect.adjusted(10, 0, -10, 0)
        tag, title, detail = entry["tag"], entry["title"], entry["detail"]
        small = QFont(option.font)
        small.setPointSizeF(max(6.5, option.font.pointSizeF() * 0.8))
        small.setWeight(QFont.Weight.Bold)
        painter.setFont(small)
        painter.setPen(QColor(theme.method_color(tag) if entry["kind"] in ("request", "history")
                              else theme.color("accent")))
        painter.drawText(QRect(rect.left(), rect.top(), 56, rect.height()), Qt.AlignmentFlag.AlignVCenter, tag)
        painter.setFont(option.font)
        painter.setPen(QColor(theme.color("text")))
        fm = painter.fontMetrics()
        title_w = min(fm.horizontalAdvance(title) + 4, int((rect.width() - 56) * 0.6))
        painter.drawText(QRect(rect.left() + 56, rect.top(), title_w, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(title, Qt.TextElideMode.ElideRight, title_w))
        painter.setPen(QColor(theme.color("text_dim")))
        drect = QRect(rect.left() + 56 + title_w + 14, rect.top(), rect.width() - 70 - title_w, rect.height())
        painter.drawText(drect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         fm.elidedText(detail, Qt.TextElideMode.ElideMiddle, drect.width()))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(100, 32)


def _score(query: str, haystack: str) -> int:
    """Higher is better; 0 = no match. Every query word must appear."""
    if not query:
        return 1
    score = 0
    for word in query.split():
        pos = haystack.find(word)
        if pos < 0:
            return 0
        score += 100 - min(pos, 90) + (20 if pos == 0 or not haystack[pos - 1].isalnum() else 0)
    return score


class CommandPalette(QDialog):
    def __init__(self, ctx, actions: List[Tuple[str, str, Callable]], open_request, open_history,
                 switch_env, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        frame = QFrame(self)
        frame.setObjectName("Popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search requests, history, environments and actions…")
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        self.list = QListWidget()
        self.list.setItemDelegate(_Delegate(self.list))
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        lay.addWidget(self.edit)
        lay.addWidget(self.list)

        self.entries = []
        for col in ctx.collections.collections:
            for req, ancestors in iter_requests(col):
                path = " / ".join(a["name"] for a in ancestors)
                self.entries.append({"kind": "request", "tag": req["method"], "title": req["name"],
                                     "detail": f"{path}  ·  {req['url']}",
                                     "run": lambda c=col["id"], r=req["id"]: open_request(c, r)})
        seen = set()
        for entry in ctx.history.entries[:60]:
            req = entry["request"]
            key = (req["method"], req["url"])
            if key in seen:
                continue
            seen.add(key)
            self.entries.append({"kind": "history", "tag": req["method"], "title": req["url"],
                                 "detail": "history", "run": lambda e=entry: open_history(e)})
        for env in ctx.envs.environments:
            self.entries.append({"kind": "env", "tag": "ENV", "title": f"Switch to environment: {env['name']}",
                                 "detail": "environment", "run": lambda i=env["id"]: switch_env(i)})
        self.entries.append({"kind": "env", "tag": "ENV", "title": "Switch to: No environment", "detail": "",
                             "run": lambda: switch_env(None)})
        for title, shortcut, fn in actions:
            self.entries.append({"kind": "action", "tag": "CMD", "title": title, "detail": shortcut, "run": fn})
        for e in self.entries:
            e["hay"] = f"{e['title']} {e['detail']} {e['tag']}".lower()
        self._filter("")

    def popup_over(self, widget):
        width = min(720, int(widget.width() * 0.8))
        top_left = widget.mapToGlobal(QPoint((widget.width() - width) // 2, 60))
        self.setGeometry(top_left.x(), top_left.y(), width, 440)
        self.show()
        self.edit.setFocus()

    def _filter(self, text: str):
        q = text.lower().strip()
        scored = []
        for i, e in enumerate(self.entries):
            s = _score(q, e["hay"])
            if s:
                scored.append((-s if q else i, i, e))
        scored.sort(key=lambda x: (x[0], x[1]))
        self.list.clear()
        for _, _, e in scored[:200]:
            item = QListWidgetItem(e["title"])
            item.setData(DATA, e)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                row = self.list.currentRow()
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 10, Qt.Key.Key_PageUp: -10}[key]
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row + step)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.list.currentItem():
                    self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, event)

    def _run(self, item):
        entry = item.data(DATA)
        self.close()
        entry["run"]()
