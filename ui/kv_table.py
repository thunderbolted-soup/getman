"""Key/value editor used for params, headers, form bodies and variables.

Postman-style: an always-present empty row at the bottom for adding,
checkboxes to disable rows, × to delete, ``{{var}}`` highlighting,
autocompletion in cells, and a "Bulk edit" text mode (``key: value`` per
line, ``//`` prefix = disabled)."""
from typing import Callable, List, Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QPlainTextEdit, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.variables import find_vars
from ui import theme
from ui.fields import SmartLineEdit, VarProvider

COL_ON, COL_KEY, COL_VALUE = 0, 1, 2


class _CellDelegate(QStyledItemDelegate):
    def __init__(self, table: "KeyValueTable"):
        super().__init__(table.table)
        self.owner = table

    def createEditor(self, parent, option, index):
        col, row = index.column(), index.row()
        if col == self.owner.type_col:
            combo = QComboBox(parent)
            combo.addItems(["Text", "File"])
            return combo
        editor = SmartLineEdit(parent, variables=self.owner.variables)
        editor.setFrame(False)
        if col == COL_KEY and self.owner.suggest_key:
            editor.set_suggest(self.owner.suggest_key)
        elif col == COL_VALUE and self.owner.suggest_value:
            key_item = self.owner.table.item(row, COL_KEY)
            key = key_item.text() if key_item else ""
            editor.set_suggest(lambda text, k=key: self.owner.suggest_value(k, text))
        return editor

    def setEditorData(self, editor, index):
        text = index.data(Qt.ItemDataRole.EditRole) or ""
        if isinstance(editor, QComboBox):
            editor.setCurrentText(text or "Text")
            editor.showPopup()
        else:
            editor.setText(text)
            editor.refresh_highlight()

    def setModelData(self, editor, model, index):
        value = editor.currentText() if isinstance(editor, QComboBox) else editor.text()
        model.setData(index, value, Qt.ItemDataRole.EditRole)

    def paint(self, painter: QPainter, option, index):
        col = index.column()
        if col == self.owner.del_col:
            super().paint(painter, option, index)
            if option.state & QStyle.StateFlag.State_MouseOver and index.row() < self.owner.table.rowCount() - 1:
                painter.save()
                painter.setPen(QColor(theme.color("text_dim")))
                painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, "×")
                painter.restore()
            return
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        spans = find_vars(text) if isinstance(text, str) else []
        is_ghost = index.row() == self.owner.table.rowCount() - 1 and self.owner.allow_add
        if not spans and not is_ghost:
            if col in (COL_KEY, COL_VALUE) and not self.owner.row_enabled(index.row()):
                option = QStyleOptionViewItem(option)  # disabled rows are dimmed
                option.palette.setColor(QPalette.ColorRole.Text, QColor(theme.color("text_faint")))
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        rect = option.rect.adjusted(6, 0, -4, 0)
        if is_ghost and not text and col in (COL_KEY, COL_VALUE):
            painter.setPen(QColor(theme.color("text_faint")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, self.owner.placeholders[col - 1])
            painter.restore()
            return
        disabled = not self.owner.row_enabled(index.row())
        known = {n for n, _, _ in self.owner.variables()} if self.owner.variables else set()
        x = rect.left()
        pos = 0
        segments = []
        for start, end, name in spans:
            segments.append((text[pos:start], None))
            segments.append((text[start:end], name))
            pos = end
        segments.append((text[pos:], None))
        bold = QFont(option.font)
        bold.setWeight(QFont.Weight.DemiBold)
        for chunk, var in segments:
            if not chunk:
                continue
            if var is None:
                painter.setFont(option.font)
                color = theme.color("text_faint" if disabled else "text")
            else:
                painter.setFont(bold)
                ok = var in known or var.startswith("$")
                color = theme.syntax("variable" if ok else "var_missing")
            painter.setPen(QColor(color))
            width = painter.fontMetrics().horizontalAdvance(chunk)
            painter.drawText(QRect(x, rect.top(), max(0, rect.right() - x), rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, chunk)
            x += width
            if x > rect.right():
                break
        painter.restore()


class KeyValueTable(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *, with_type: bool = False, allow_add: bool = True,
                 key_editable: bool = True, checkable: bool = True,
                 variables: Optional[VarProvider] = None,
                 suggest_key: Callable[[str], List[str]] = None,
                 suggest_value: Callable[[str, str], List[str]] = None,
                 placeholders=("Key", "Value"), bulk: bool = True):
        super().__init__(parent)
        self.with_type = with_type
        self.allow_add = allow_add
        self.key_editable = key_editable
        self.checkable = checkable
        self.variables = variables
        self.suggest_key = suggest_key
        self.suggest_value = suggest_value
        self.placeholders = placeholders
        self.type_col = 3 if with_type else -1
        self.del_col = 4 if with_type else 3
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget()
        self.table = QTableWidget(0, self.del_col + 1)
        labels = ["", placeholders[0], placeholders[1]] + (["Type"] if with_type else []) + [""]
        self.table.setHorizontalHeaderLabels(labels)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(True)
        self.table.setMouseTracking(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.SelectedClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_ON, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_KEY, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Stretch)
        if with_type:
            hh.setSectionResizeMode(self.type_col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(self.type_col, 70)
        hh.setSectionResizeMode(self.del_col, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_ON, 30)
        self.table.setColumnWidth(COL_KEY, 220)
        self.table.setColumnWidth(self.del_col, 30)
        hh.setHighlightSections(False)
        if not checkable:
            self.table.setColumnHidden(COL_ON, True)
        if not allow_add:
            self.table.setColumnHidden(self.del_col, True)
        self.table.setItemDelegate(_CellDelegate(self))
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.stack.addWidget(self.table)

        self.bulk_edit: Optional[QPlainTextEdit] = None  # created on first use
        lay.addWidget(self.stack)

        self.bulk_btn = None
        if bulk and allow_add:
            bar = QHBoxLayout()
            bar.setContentsMargins(0, 0, 0, 0)
            bar.addStretch()
            self.bulk_btn = QPushButton("Bulk edit")
            self.bulk_btn.setObjectName("Link")
            self.bulk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.bulk_btn.clicked.connect(self.toggle_bulk)
            bar.addWidget(self.bulk_btn)
            lay.insertLayout(0, bar)
        self.set_rows([])

    # --- rows --------------------------------------------------------------------
    def _make_row(self, row: int, data: Optional[dict]):
        t = self.table
        ghost = data is None
        data = data or {"key": "", "value": "", "enabled": True, "type": "text"}
        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsUserCheckable if not ghost else Qt.ItemFlag.NoItemFlags))
        if not ghost:
            on.setCheckState(Qt.CheckState.Checked if data.get("enabled", True) else Qt.CheckState.Unchecked)
        t.setItem(row, COL_ON, on)
        key = QTableWidgetItem(data.get("key", ""))
        if not self.key_editable:
            key.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            key.setForeground(QColor(theme.color("text_dim")))
        t.setItem(row, COL_KEY, key)
        value = QTableWidgetItem(data.get("value", ""))
        is_file = self.with_type and data.get("type") == "file"
        if is_file:
            value.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            value.setToolTip("Double-click to choose a file")
        t.setItem(row, COL_VALUE, value)
        if self.with_type:
            t.setItem(row, self.type_col, QTableWidgetItem("File" if is_file else "Text"))
        delete = QTableWidgetItem()
        delete.setFlags(Qt.ItemFlag.ItemIsEnabled)
        delete.setToolTip("Delete row")
        t.setItem(row, self.del_col, delete)

    def set_rows(self, rows: List[dict]):
        self._loading = True
        self.table.setRowCount(0)
        rows = rows or []
        self.table.setRowCount(len(rows) + (1 if self.allow_add else 0))
        for i, r in enumerate(rows):
            self._make_row(i, r)
        if self.allow_add:
            self._make_row(len(rows), None)
        self._loading = False
        if self.stack.currentIndex() == 1:
            self.bulk_edit.setPlainText(self._rows_to_text(rows))

    def rows(self) -> List[dict]:
        if self.stack.currentIndex() == 1:
            return self._text_to_rows(self.bulk_edit.toPlainText())
        out = []
        n = self.table.rowCount() - (1 if self.allow_add else 0)
        for i in range(n):
            key = self.table.item(i, COL_KEY).text() if self.table.item(i, COL_KEY) else ""
            value = self.table.item(i, COL_VALUE).text() if self.table.item(i, COL_VALUE) else ""
            row = {"key": key, "value": value, "enabled": self.row_enabled(i)}
            if self.with_type:
                type_item = self.table.item(i, self.type_col)
                row["type"] = "file" if type_item and type_item.text() == "File" else "text"
            out.append(row)
        return out

    def row_enabled(self, row: int) -> bool:
        item = self.table.item(row, COL_ON)
        if not self.checkable:
            return True
        return bool(item and item.checkState() == Qt.CheckState.Checked)

    def enabled_count(self) -> int:
        return sum(1 for r in self.rows() if r["enabled"] and r["key"])

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        row = item.row()
        last = self.table.rowCount() - 1
        if self.allow_add and row == last and item.column() in (COL_KEY, COL_VALUE) and item.text():
            self._loading = True
            on = self.table.item(row, COL_ON)
            on.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            on.setCheckState(Qt.CheckState.Checked)
            self.table.insertRow(last + 1)
            self._make_row(last + 1, None)
            self._loading = False
        if self.with_type and item.column() == self.type_col:
            self._loading = True
            value = self.table.item(row, COL_VALUE)
            if item.text() == "File":
                value.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                value.setText("")
            else:
                value.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
            self._loading = False
        if item.column() == COL_ON:
            self.table.viewport().update()
        self.changed.emit()

    def _on_cell_clicked(self, row, col):
        if col == self.del_col and self.allow_add and row < self.table.rowCount() - 1:
            self.table.removeRow(row)
            self.changed.emit()

    def _on_cell_double_clicked(self, row, col):
        if col != COL_VALUE or not self.with_type:
            return
        type_item = self.table.item(row, self.type_col)
        if type_item and type_item.text() == "File":
            path, _ = QFileDialog.getOpenFileName(self, "Choose file")
            if path:
                self.table.item(row, COL_VALUE).setText(path)

    # --- bulk mode ------------------------------------------------------------------
    @staticmethod
    def _rows_to_text(rows: List[dict]) -> str:
        return "\n".join(("" if r.get("enabled", True) else "//") + f"{r['key']}: {r.get('value', '')}"
                         for r in rows if r.get("key") or r.get("value"))

    def _text_to_rows(self, text: str) -> List[dict]:
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            enabled = not line.lstrip().startswith("//")
            line = line.lstrip()[2:] if not enabled else line
            key, sep, value = line.partition(":")
            row = {"key": key.strip(), "value": value.strip() if sep else "", "enabled": enabled}
            if self.with_type:
                row["type"] = "text"
            rows.append(row)
        return rows

    def _ensure_bulk(self) -> QPlainTextEdit:
        if self.bulk_edit is None:
            self.bulk_edit = QPlainTextEdit()
            self.bulk_edit.setFont(theme.mono_font())
            self.bulk_edit.setPlaceholderText("key: value\n// disabled: value")
            self.bulk_edit.textChanged.connect(lambda: self.stack.currentIndex() == 1 and self.changed.emit())
            self.stack.addWidget(self.bulk_edit)
        return self.bulk_edit

    def toggle_bulk(self):
        if self.stack.currentIndex() == 0:
            self._ensure_bulk()
            self.bulk_edit.setPlainText(self._rows_to_text(self.rows()))
            self.stack.setCurrentIndex(1)
            self.bulk_btn.setText("Key-value edit")
            self.bulk_edit.setFocus()
        else:
            rows = self._text_to_rows(self.bulk_edit.toPlainText())
            self.stack.setCurrentIndex(0)
            self.set_rows(rows)
            self.bulk_btn.setText("Bulk edit")
            self.changed.emit()

    def refresh_highlight(self):
        self.table.viewport().update()

