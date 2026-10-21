"""Auth settings editor shared by requests, folders and collections.
Each auth type's form is built the first time it is selected."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from core.models import new_auth
from ui.fields import SmartLineEdit

TYPES = [("inherit", "Inherit from parent"), ("none", "No auth"), ("bearer", "Bearer token"),
         ("basic", "Basic auth"), ("apikey", "API key")]
_FIELDS = {"bearer": ("token",), "basic": ("username", "password"), "apikey": ("key", "value", "in")}


class AuthEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None, allow_inherit: bool = True, variables=None):
        super().__init__(parent)
        self._loading = False
        self._auth = new_auth()
        self._variables = variables
        self._hint_text = "This request uses the auth of its folder or collection."
        self.pages = {}
        self.fields = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 4)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Type"))
        self.type_combo = QComboBox()
        for key, label in TYPES:
            if key == "inherit" and not allow_inherit:
                continue
            self.type_combo.addItem(label, key)
        top.addWidget(self.type_combo)
        top.addStretch()
        lay.addLayout(top)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        lay.addStretch()
        self.type_combo.currentIndexChanged.connect(self._on_type)

    # --- lazy pages ----------------------------------------------------------------
    def _page(self, auth_type: str) -> QWidget:
        page = self.pages.get(auth_type)
        if page is not None:
            return page
        if auth_type in ("inherit", "none"):
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(0, 0, 0, 0)
            label = QLabel(self._hint_text if auth_type == "inherit" else "No authorization data will be sent.")
            label.setObjectName("Dim")
            label.setWordWrap(True)
            pl.addWidget(label)
            pl.addStretch()
            if auth_type == "inherit":
                self.hint = label
        else:
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(0, 0, 0, 0)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for name in _FIELDS[auth_type]:
                if name == "in":
                    combo = QComboBox()
                    combo.addItem("Header", "header")
                    combo.addItem("Query params", "query")
                    combo.setCurrentIndex(1 if self._auth["in"] == "query" else 0)
                    combo.currentIndexChanged.connect(lambda _i, c=combo: self._set("in", c.currentData()))
                    form.addRow("Add to", combo)
                    self.fields["in"] = combo
                    continue
                edit = SmartLineEdit(variables=self._variables)
                edit.setText(self._auth[name])
                edit.textChanged.connect(lambda text, n=name: self._set(n, text))
                self.fields[name] = edit
                label = name.capitalize()
                if name == "token":
                    edit.setPlaceholderText("Token or {{variable}}")
                elif name == "key":
                    edit.setPlaceholderText("X-API-Key")
                if name == "password":
                    edit.setEchoMode(QLineEdit.EchoMode.Password)
                    row = QWidget()
                    rl = QHBoxLayout(row)
                    rl.setContentsMargins(0, 0, 0, 0)
                    rl.addWidget(edit)
                    eye = QToolButton()
                    eye.setText("👁")
                    eye.setCheckable(True)
                    eye.setToolTip("Show password")
                    eye.toggled.connect(lambda on, e=edit: e.setEchoMode(
                        QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
                    rl.addWidget(eye)
                    form.addRow(label, row)
                else:
                    form.addRow(label, edit)
        self.pages[auth_type] = page
        self.stack.addWidget(page)
        return page

    def _set(self, name: str, value: str):
        self._auth[name] = value
        if not self._loading:
            self.changed.emit()

    def _on_type(self):
        self._auth["type"] = self.type_combo.currentData()
        self.stack.setCurrentWidget(self._page(self._auth["type"]))
        if not self._loading:
            self.changed.emit()

    # --- API ------------------------------------------------------------------------
    def set_inherit_hint(self, text: str):
        self._hint_text = text
        if "inherit" in self.pages:
            self.hint.setText(text)

    def set_auth(self, auth: dict):
        self._loading = True
        self._auth = dict(new_auth(), **(auth or {}))
        for name, widget in self.fields.items():
            if name == "in":
                widget.setCurrentIndex(1 if self._auth["in"] == "query" else 0)
            else:
                widget.setText(self._auth[name])
        index = self.type_combo.findData(self._auth["type"])
        self.type_combo.setCurrentIndex(max(index, 0))
        self._auth["type"] = self.type_combo.currentData()
        self.stack.setCurrentWidget(self._page(self._auth["type"]))
        self._loading = False

    def auth(self) -> dict:
        return dict(self._auth)

    def refresh_highlight(self):
        for name, widget in self.fields.items():
            if name != "in":
                widget.refresh_highlight()
