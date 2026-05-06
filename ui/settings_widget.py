from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QCheckBox, 
                             QLineEdit, QPushButton, QLabel, QDialog)
from core.settings import get_settings, save_settings

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(400, 200)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.settings = get_settings()
        
        self.ssl_check = QCheckBox("Verify SSL Certificates")
        self.ssl_check.setChecked(self.settings.get("verify_ssl", True))
        form.addRow("SSL:", self.ssl_check)
        
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("e.g. http://127.0.0.1:8080")
        self.proxy_edit.setText(self.settings.get("proxy_url", ""))
        form.addRow("Proxy:", self.proxy_edit)
        
        layout.addLayout(form)
        
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.on_save)
        layout.addWidget(self.save_btn)

    def on_save(self):
        new_settings = {
            "verify_ssl": self.ssl_check.isChecked(),
            "proxy_url": self.proxy_edit.text().strip()
        }
        save_settings(new_settings)
        self.accept()
