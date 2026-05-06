from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                             QComboBox, QLineEdit, QPushButton, QTabWidget, 
                             QTableWidget, QTableWidgetItem, QHeaderView, 
                             QPlainTextEdit, QRadioButton, QButtonGroup, QDialog, QStackedWidget)
from PySide6.QtCore import Qt, Signal, QUrl
from ui.auth_widget import AuthManagementWidget
from ui.json_editor import CodeEditor, PythonCodeEditor
from ui.shared_widgets import KeyValueTable, FormDataTable
from core.auth import get_auth_entries, get_last_auth_for_host, set_last_auth_for_host, get_auth_by_id

class RequestPanel(QWidget):
    send_requested = Signal(str, str, dict, str, dict, str) # method, url, headers, body, params, pre_script
    curl_requested = Signal(str, str, dict, object, dict, str) # method, url, headers, body, params, pre_script
    cancel_requested = Signal()
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
        
        self.curl_btn = QPushButton("cURL")
        self.curl_btn.setToolTip("Copy as cURL")
        self.curl_btn.clicked.connect(self.on_copy_curl_clicked)
        
        url_layout.addWidget(self.method_combo)
        url_layout.addWidget(self.url_edit)
        url_layout.addWidget(self.send_btn)
        url_layout.addWidget(self.save_btn)
        url_layout.addWidget(self.curl_btn)
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
        self.json_edit = CodeEditor()
        self.json_edit.setPlaceholderText('{\n  "key": "value"\n}')
        self.body_stack.addWidget(self.json_edit)
        
        # Form data page
        self.form_table = FormDataTable()
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
        
        # Pre-request Script Tab
        prereq_container = QWidget()
        prereq_layout = QVBoxLayout(prereq_container)
        prereq_layout.setContentsMargins(4, 4, 4, 4)
        prereq_layout.addWidget(QLabel("Python script executed before each request. Modify 'env' dict to inject variables."))
        self.prereq_editor = PythonCodeEditor()
        prereq_layout.addWidget(self.prereq_editor)
        self.tabs.addTab(prereq_container, "Pre-request")
        
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
        if self.send_btn.text() == "Cancel":
            self.cancel_requested.emit()
            return

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
            # Pass the list of form items
            body = self.form_table.get_data()
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
        
        self.send_requested.emit(method, url, headers, body, params, self.prereq_editor.toPlainText())

    def on_save_clicked(self):
        body_data = ""
        if self.json_rb.isChecked(): body_data = self.json_edit.toPlainText()
        elif self.form_rb.isChecked(): body_data = self.form_table.get_data()
        elif self.urlencode_rb.isChecked(): body_data = self.urlencode_table.get_data()
            
        data = {
            "method": self.method_combo.currentText(),
            "url": self.url_edit.text(),
            "headers": self.headers_table.get_data(),
            "params": self.params_table.get_data(),
            "body_type": self.body_type_group.checkedButton().text(),
            "body": body_data,
            "pre_request_script": self.prereq_editor.toPlainText()
        }
        self.save_requested.emit(data)

    def on_copy_curl_clicked(self):
        method = self.method_combo.currentText()
        url = self.url_edit.text()
        headers = self.headers_table.get_data()
        params = self.params_table.get_data()
        pre_script = self.prereq_editor.toPlainText()
        
        body = None
        if self.json_rb.isChecked(): 
            body = self.json_edit.toPlainText()
        elif self.form_rb.isChecked(): 
            body = self.form_table.get_data()
        elif self.urlencode_rb.isChecked(): 
            body = self.urlencode_table.get_data()
            
        self.curl_requested.emit(method, url, headers, body, params, pre_script)

    def set_sending_state(self, is_sending: bool):
        if is_sending:
            self.send_btn.setText("Cancel")
            self.send_btn.setStyleSheet("background-color: #c0392b; color: white;")
        else:
            self.send_btn.setText("Send")
            self.send_btn.setStyleSheet("")

    def get_selected_auth(self):
        auth_id = self.auth_profile_combo.currentData()
        if auth_id:
            from core.auth import get_auth_by_id
            return get_auth_by_id(auth_id)
        return None



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
        if isinstance(body_obj, dict) and "mode" in body_obj:
            mode = body_obj.get("mode")
            if mode == "raw":
                self.json_rb.setChecked(True)
                self.body_stack.setCurrentIndex(1)
                self.json_edit.setPlainText(body_obj.get("raw", ""))
            elif mode == "formdata":
                self.form_rb.setChecked(True)
                self.body_stack.setCurrentIndex(2)
                self.form_table.set_data(body_obj.get("formdata", []))
            elif mode == "urlencoded":
                self.urlencode_rb.setChecked(True)
                self.body_stack.setCurrentIndex(3)
                self.urlencode_table.set_data(body_obj.get("urlencoded", []))
            else:
                self.none_rb.setChecked(True)
                self.body_stack.setCurrentIndex(0)
        else:
            # History or internal format
            body_type = data.get("body_type", "none")
            if body_type == "raw JSON":
                self.json_rb.setChecked(True)
                self.body_stack.setCurrentIndex(1)
                self.json_edit.setPlainText(str(body_obj))
            elif body_type == "form-data":
                self.form_rb.setChecked(True)
                self.body_stack.setCurrentIndex(2)
                self.form_table.set_data(body_obj if isinstance(body_obj, list) else [])
            elif body_type == "x-www-form-urlencoded":
                self.urlencode_rb.setChecked(True)
                self.body_stack.setCurrentIndex(3)
                self.urlencode_table.set_data(body_obj if isinstance(body_obj, dict) else {})
            else:
                self.none_rb.setChecked(True)
                self.body_stack.setCurrentIndex(0)
        
        # Restore pre-request script if available
        script = data.get("pre_request_script", "")
        self.prereq_editor.setPlainText(script)
