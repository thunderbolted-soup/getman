from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox, 
                             QLineEdit, QPushButton, QHBoxLayout, QListWidget, QStackedWidget, QFormLayout, QListWidgetItem)
from PySide6.QtCore import Signal, Qt
from core.auth import get_auth_entries, save_auth_entry, delete_auth_entry

class AuthManagementWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        
        # Left side: List of profiles
        left_layout = QVBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self.on_profile_selected)
        left_layout.addWidget(self.profile_list)
        
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self.on_add_clicked)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.on_delete_clicked)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.del_btn)
        left_layout.addLayout(btn_layout)
        layout.addLayout(left_layout)
        
        # Right side: Edit form
        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        
        self.name_edit = QLineEdit()
        self.form_layout.addRow("Name:", self.name_edit)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["basic", "bearer", "apikey"])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.form_layout.addRow("Type:", self.type_combo)
        
        self.stack = QStackedWidget()
        
        # Basic Auth Page
        self.basic_page = QWidget()
        basic_layout = QFormLayout(self.basic_page)
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        basic_layout.addRow("Username:", self.username_edit)
        basic_layout.addRow("Password:", self.password_edit)
        self.stack.addWidget(self.basic_page)
        
        # Bearer Page
        self.bearer_page = QWidget()
        bearer_layout = QFormLayout(self.bearer_page)
        self.token_edit = QLineEdit()
        bearer_layout.addRow("Token:", self.token_edit)
        self.stack.addWidget(self.bearer_page)
        
        # API Key Page
        self.apikey_page = QWidget()
        apikey_layout = QFormLayout(self.apikey_page)
        self.key_header_edit = QLineEdit()
        self.key_value_edit = QLineEdit()
        apikey_layout.addRow("Header/Param:", self.key_header_edit)
        apikey_layout.addRow("Value:", self.key_value_edit)
        self.stack.addWidget(self.apikey_page)
        
        self.form_layout.addRow(self.stack)
        
        self.save_btn = QPushButton("Save Profile")
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.form_layout.addRow(self.save_btn)
        
        layout.addWidget(self.form_widget)
        self.form_widget.setEnabled(False)
        
        self.current_id = None
        self.refresh()

    def refresh(self):
        self.profile_list.clear()
        for entry in get_auth_entries():
            item = QListWidgetItem(entry["name"])
            item.setData(Qt.UserRole, entry)
            self.profile_list.addItem(item)

    def on_type_changed(self, type_text):
        if type_text == "basic": self.stack.setCurrentIndex(0)
        elif type_text == "bearer": self.stack.setCurrentIndex(1)
        elif type_text == "apikey": self.stack.setCurrentIndex(2)

    def on_add_clicked(self):
        self.current_id = None
        self.name_edit.setText("New Profile")
        self.type_combo.setCurrentIndex(0)
        self.username_edit.clear()
        self.password_edit.clear()
        self.token_edit.clear()
        self.key_header_edit.clear()
        self.key_value_edit.clear()
        self.form_widget.setEnabled(True)

    def on_profile_selected(self, item):
        entry = item.data(Qt.UserRole)
        self.current_id = entry["id"]
        self.name_edit.setText(entry["name"])
        self.type_combo.setCurrentText(entry["type"])
        data = entry["data"]
        
        if entry["type"] == "basic":
            self.username_edit.setText(data.get("username", ""))
            self.password_edit.setText(data.get("password", ""))
        elif entry["type"] == "bearer":
            self.token_edit.setText(data.get("token", ""))
        elif entry["type"] == "apikey":
            self.key_header_edit.setText(data.get("key", ""))
            self.key_value_edit.setText(data.get("value", ""))
            
        self.form_widget.setEnabled(True)

    def on_save_clicked(self):
        name = self.name_edit.text()
        auth_type = self.type_combo.currentText()
        auth_data = {}
        
        if auth_type == "basic":
            auth_data = {"username": self.username_edit.text(), "password": self.password_edit.text()}
        elif auth_type == "bearer":
            auth_data = {"token": self.token_edit.text()}
        elif auth_type == "apikey":
            auth_data = {"key": self.key_header_edit.text(), "value": self.key_value_edit.text()}
            
        save_auth_entry(name, auth_type, auth_data, self.current_id)
        self.refresh()
        self.changed.emit()

    def on_delete_clicked(self):
        item = self.profile_list.currentItem()
        if item:
            entry = item.data(Qt.UserRole)
            delete_auth_entry(entry["id"])
            self.current_id = None
            self.form_widget.setEnabled(False)
            self.refresh()
            self.changed.emit()
