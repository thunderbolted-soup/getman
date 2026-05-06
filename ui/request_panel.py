from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                             QComboBox, QLineEdit, QPushButton, QTabWidget, 
                             QTableWidget, QTableWidgetItem, QHeaderView, 
                             QPlainTextEdit, QRadioButton, QButtonGroup, QDialog, QStackedWidget)
from PySide6.QtCore import Qt, Signal, QUrl
from ui.auth_widget import AuthManagementWidget
from core.auth import get_auth_entries, get_last_auth_for_host, set_last_auth_for_host, get_auth_by_id

class KeyValueTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["", "Key", "Value"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 30)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.add_empty_row()
        self.itemChanged.connect(self.on_item_changed)

    def add_empty_row(self):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)
        
        check_item = QTableWidgetItem()
        check_item.setCheckState(Qt.Checked)
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        self.setItem(row, 0, check_item)
        
        self.setItem(row, 1, QTableWidgetItem(""))
        self.setItem(row, 2, QTableWidgetItem(""))
        self.blockSignals(False)

    def on_item_changed(self, item):
        if item.row() == self.rowCount() - 1:
            key_item = self.item(item.row(), 1)
            if key_item and key_item.text():
                self.add_empty_row()

    def get_data(self) -> dict:
        data = {}
        for row in range(self.rowCount()):
            check_item = self.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                key_item = self.item(row, 1)
                val_item = self.item(row, 2)
                if key_item and key_item.text():
                    data[key_item.text()] = val_item.text() if val_item else ""
        return data

    def set_data(self, data: dict):
        self.setRowCount(0)
        for key, value in data.items():
            row = self.rowCount()
            self.insertRow(row)
            check_item = QTableWidgetItem()
            check_item.setCheckState(Qt.Checked)
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            self.setItem(row, 0, check_item)
            self.setItem(row, 1, QTableWidgetItem(str(key)))
            self.setItem(row, 2, QTableWidgetItem(str(value)))
        self.add_empty_row()

class RequestPanel(QWidget):
    send_requested = Signal(str, str, dict, str, dict) # method, url, headers, body, params
    save_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # URL Bar
        url_layout = QHBoxLayout()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Enter URL")
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send_clicked)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.on_save_clicked)
        
        url_layout.addWidget(self.method_combo)
        url_layout.addWidget(self.url_edit)
        url_layout.addWidget(self.send_btn)
        url_layout.addWidget(self.save_btn)
        layout.addLayout(url_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        
        self.params_table = KeyValueTable()
        self.tabs.addTab(self.params_table, "Params")
        
        self.headers_table = KeyValueTable()
        self.tabs.addTab(self.headers_table, "Headers")
        
        # Body Tab
        body_container = QWidget()
        body_main_layout = QVBoxLayout(body_container)
        
        # Body type selection
        type_layout = QHBoxLayout()
        self.body_type_group = QButtonGroup(self)
        self.none_rb = QRadioButton("none")
        self.none_rb.setChecked(True)
        self.json_rb = QRadioButton("raw JSON")
        self.form_rb = QRadioButton("form-data")
        self.urlencode_rb = QRadioButton("x-www-form-urlencoded")
        
        for rb in [self.none_rb, self.json_rb, self.form_rb, self.urlencode_rb]:
            self.body_type_group.addButton(rb)
            type_layout.addWidget(rb)
        type_layout.addStretch()
        body_main_layout.addLayout(type_layout)
        
        self.body_stack = QStackedWidget()
        
        # None page
        self.body_stack.addWidget(QLabel("This request does not have a body."))
        
        # Raw JSON page
        self.json_edit = QPlainTextEdit()
        self.json_edit.setPlaceholderText('{\n  "key": "value"\n}')
        self.body_stack.addWidget(self.json_edit)
        
        # Form data page
        self.form_table = KeyValueTable()
        self.body_stack.addWidget(self.form_table)
        
        # URL encoded page
        self.urlencode_table = KeyValueTable()
        self.body_stack.addWidget(self.urlencode_table)
        
        body_main_layout.addWidget(self.body_stack)
        self.tabs.addTab(body_container, "Body")
        
        self.body_type_group.buttonClicked.connect(self.on_body_type_changed)
        
        # Auth Tab
        self.auth_widget = QWidget()
        auth_layout = QVBoxLayout(self.auth_widget)
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Auth Profile:"))
        self.auth_profile_combo = QComboBox()
        profile_layout.addWidget(self.auth_profile_combo)
        self.manage_auth_btn = QPushButton("Manage...")
        self.manage_auth_btn.clicked.connect(self.on_manage_auth_clicked)
        profile_layout.addWidget(self.manage_auth_btn)
        auth_layout.addLayout(profile_layout)
        auth_layout.addStretch()
        self.tabs.addTab(self.auth_widget, "Auth")
        
        layout.addWidget(self.tabs)
        self.url_edit.textChanged.connect(self.on_url_changed)
        self.refresh_auth_profiles()

    def on_body_type_changed(self, button):
        if button == self.none_rb: self.body_stack.setCurrentIndex(0)
        elif button == self.json_rb: self.body_stack.setCurrentIndex(1)
        elif button == self.form_rb: self.body_stack.setCurrentIndex(2)
        elif button == self.urlencode_rb: self.body_stack.setCurrentIndex(3)

    def refresh_auth_profiles(self):
        self.auth_profile_combo.clear()
        self.auth_profile_combo.addItem("None", None)
        for entry in get_auth_entries():
            self.auth_profile_combo.addItem(entry["name"], entry["id"])

    def on_manage_auth_clicked(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage Auth Profiles")
        dialog.resize(600, 400)
        d_layout = QVBoxLayout(dialog)
        manage_widget = AuthManagementWidget()
        manage_widget.changed.connect(self.refresh_auth_profiles)
        d_layout.addWidget(manage_widget)
        dialog.exec()

    def on_url_changed(self, text):
        url = QUrl(text)
        host = url.host()
        if host:
            auth_id = get_last_auth_for_host(host)
            if auth_id:
                index = self.auth_profile_combo.findData(auth_id)
                if index >= 0:
                    self.auth_profile_combo.setCurrentIndex(index)

    def on_send_clicked(self):
        method = self.method_combo.currentText()
        url = self.url_edit.text()
        headers = self.headers_table.get_data()
        params = self.params_table.get_data()
        
        body = ""
        if self.json_rb.isChecked():
            body = self.json_edit.toPlainText()
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif self.form_rb.isChecked():
            # Minimal form-data support (just as string for now)
            body = str(self.form_table.get_data())
        elif self.urlencode_rb.isChecked():
            body = str(self.urlencode_table.get_data())
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        auth_id = self.auth_profile_combo.currentData()
        if auth_id:
            auth_entry = get_auth_by_id(auth_id)
            if auth_entry:
                self.apply_auth(headers, auth_entry)
                host = QUrl(url).host()
                if host:
                    set_last_auth_for_host(host, auth_id)
        
        self.send_requested.emit(method, url, headers, body, params)

    def on_save_clicked(self):
        data = {
            "method": self.method_combo.currentText(),
            "url": self.url_edit.text(),
            "headers": self.headers_table.get_data(),
            "params": self.params_table.get_data(),
            "body_type": self.body_type_group.checkedButton().text(),
            "body": self.json_edit.toPlainText() if self.json_rb.isChecked() else ""
        }
        self.save_requested.emit(data)

    def apply_auth(self, headers, auth_entry):
        import base64
        a_type = auth_entry["type"]
        data = auth_entry["data"]
        if a_type == "bearer":
            headers["Authorization"] = f"Bearer {data.get('token', '')}"
        elif a_type == "basic":
            user = data.get("username", "")
            pw = data.get("password", "")
            auth_str = base64.b64encode(f"{user}:{pw}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
        elif a_type == "apikey":
            key = data.get("key", "X-Api-Key")
            val = data.get("value", "")
            headers[key] = val

    def set_request_data(self, data: dict):
        method = data.get("method", "GET")
        index = self.method_combo.findText(method)
        if index >= 0: self.method_combo.setCurrentIndex(index)
        
        url = data.get("url", "")
        if isinstance(url, dict): url = url.get("raw", "")
        self.url_edit.setText(url)
        
        headers = data.get("headers", {})
        if not headers:
            headers_list = data.get("header", [])
            if isinstance(headers_list, list):
                headers = {h.get("key"): h.get("value") for h in headers_list if h.get("key")}
        self.headers_table.set_data(headers)
        
        params = data.get("params", {})
        if not params and isinstance(data.get("url"), dict):
            query_list = data["url"].get("query", [])
            if isinstance(query_list, list):
                params = {q.get("key"): q.get("value") for q in query_list if q.get("key")}
        self.params_table.set_data(params)
        
        body_obj = data.get("body", "")
        if isinstance(body_obj, dict):
            mode = body_obj.get("mode")
            if mode == "raw":
                self.json_rb.setChecked(True)
                self.body_stack.setCurrentIndex(1)
                self.json_edit.setPlainText(body_obj.get("raw", ""))
            else:
                self.none_rb.setChecked(True)
                self.body_stack.setCurrentIndex(0)
        else:
            # History or internal format
            self.json_edit.setPlainText(str(body_obj))
            if body_obj:
                self.json_rb.setChecked(True)
                self.body_stack.setCurrentIndex(1)
            else:
                self.none_rb.setChecked(True)
                self.body_stack.setCurrentIndex(0)
