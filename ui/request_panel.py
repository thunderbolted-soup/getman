from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                             QComboBox, QLineEdit, QPushButton, QTabWidget, 
                             QTableWidget, QTableWidgetItem, QHeaderView, 
                             QPlainTextEdit, QRadioButton, QButtonGroup, QDialog)
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
        
        url_layout.addWidget(self.method_combo)
        url_layout.addWidget(self.url_edit)
        url_layout.addWidget(self.send_btn)
        layout.addLayout(url_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        
        self.params_table = KeyValueTable()
        self.tabs.addTab(self.params_table, "Params")
        
        self.headers_table = KeyValueTable()
        self.tabs.addTab(self.headers_table, "Headers")
        
        # Body Tab
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        self.body_edit = QPlainTextEdit()
        body_layout.addWidget(self.body_edit)
        self.tabs.addTab(body_widget, "Body")
        
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
        
        # Track URL changes for smart auth
        self.url_edit.textChanged.connect(self.on_url_changed)
        
        # Initial refresh
        self.refresh_auth_profiles()

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
        body = self.body_edit.toPlainText()
        
        # Apply selected auth to headers
        auth_id = self.auth_profile_combo.currentData()
        if auth_id:
            auth_entry = get_auth_by_id(auth_id)
            if auth_entry:
                self.apply_auth(headers, auth_entry)
                # Remember this auth for this host
                host = QUrl(url).host()
                if host:
                    set_last_auth_for_host(host, auth_id)
        
        self.send_requested.emit(method, url, headers, body, params)

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
        """Loads request data into the UI. Handles both Postman and internal history formats."""
        # Method
        method = data.get("method", "GET")
        index = self.method_combo.findText(method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
            
        # URL
        url = data.get("url", "")
        if isinstance(url, dict):
            url = url.get("raw", "")
        self.url_edit.setText(url)
        
        # Headers
        headers = data.get("headers", {})
        if not headers:
            headers_list = data.get("header", [])
            if isinstance(headers_list, list):
                headers = {h.get("key"): h.get("value") for h in headers_list if h.get("key")}
        self.headers_table.set_data(headers)
        
        # Params
        params = data.get("params", {})
        if not params and isinstance(data.get("url"), dict):
            query_list = data["url"].get("query", [])
            if isinstance(query_list, list):
                params = {q.get("key"): q.get("value") for q in query_list if q.get("key")}
        self.params_table.set_data(params)
        
        # Body
        body = data.get("body", "")
        if isinstance(body, dict):
            mode = body.get("mode")
            if mode == "raw":
                body = body.get("raw", "")
            else:
                body = ""
        self.body_edit.setPlainText(str(body))
