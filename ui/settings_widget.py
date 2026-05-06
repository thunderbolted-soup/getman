from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QCheckBox, 
                             QLineEdit, QPushButton, QLabel, QDialog, QSpinBox, 
                             QComboBox, QHBoxLayout, QFileDialog, QMessageBox)
from core.settings import get_settings, save_settings
from ui.shared_widgets import KeyValueTable
import os
import shutil
import zipfile
from datetime import datetime

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(600, 500)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.settings = get_settings()
        
        # SSL & Proxy
        self.ssl_check = QCheckBox("Verify SSL Certificates")
        self.ssl_check.setChecked(self.settings.get("verify_ssl", True))
        form.addRow("SSL:", self.ssl_check)
        
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("e.g. http://127.0.0.1:8080")
        self.proxy_edit.setText(self.settings.get("proxy_url", ""))
        form.addRow("Proxy:", self.proxy_edit)
        
        # Limits
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setSuffix(" sec")
        self.timeout_spin.setValue(self.settings.get("request_timeout", 60))
        form.addRow("Request Timeout:", self.timeout_spin)
        
        self.history_spin = QSpinBox()
        self.history_spin.setRange(0, 5000)
        self.history_spin.setValue(self.settings.get("max_history_size", 100))
        form.addRow("Max History Size:", self.history_spin)
        
        # Theme
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.settings.get("theme", "dark"))
        form.addRow("Theme:", self.theme_combo)
        
        layout.addLayout(form)
        
        # Default Headers
        layout.addWidget(QLabel("Default Headers (applied to all requests):"))
        self.headers_table = KeyValueTable()
        self.headers_table.set_data(self.settings.get("default_headers", {}))
        layout.addWidget(self.headers_table)
        
        # Backup / Restore
        backup_layout = QHBoxLayout()
        self.export_btn = QPushButton("Export Data (ZIP)")
        self.export_btn.clicked.connect(self.on_export_data)
        self.import_btn = QPushButton("Import Data (ZIP)")
        self.import_btn.clicked.connect(self.on_import_data)
        backup_layout.addWidget(self.export_btn)
        backup_layout.addWidget(self.import_btn)
        layout.addLayout(backup_layout)

        # Save
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.on_save)
        layout.addWidget(self.save_btn)

    def on_save(self):
        new_settings = {
            "verify_ssl": self.ssl_check.isChecked(),
            "proxy_url": self.proxy_edit.text().strip(),
            "request_timeout": self.timeout_spin.value(),
            "max_history_size": self.history_spin.value(),
            "theme": self.theme_combo.currentText(),
            "default_headers": self.headers_table.get_data()
        }
        save_settings(new_settings)
        self.accept()

    def on_export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Getman Data", 
                                                  f"getman_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", 
                                                  "ZIP Files (*.zip)")
        if file_path:
            try:
                with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk("data"):
                        for file in files:
                            zipf.write(os.path.join(root, file), 
                                       os.path.relpath(os.path.join(root, file), os.path.join("data", "..")))
                QMessageBox.information(self, "Export Success", f"Data exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {str(e)}")

    def on_import_data(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Getman Data", "", "ZIP Files (*.zip)")
        if file_path:
            confirm = QMessageBox.question(self, "Confirm Import", 
                                         "This will overwrite your current data. Are you sure?",
                                         QMessageBox.Yes | QMessageBox.No)
            if confirm == QMessageBox.Yes:
                try:
                    with zipfile.ZipFile(file_path, 'r') as zipf:
                        zipf.extractall(".")
                    QMessageBox.information(self, "Import Success", "Data imported successfully. Please restart the app.")
                except Exception as e:
                    QMessageBox.critical(self, "Import Error", f"Failed to import: {str(e)}")
