from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QComboBox, QLineEdit, QPushButton, QTabWidget

class RequestPanel(QWidget):
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
        
        url_layout.addWidget(self.method_combo)
        url_layout.addWidget(self.url_edit)
        url_layout.addWidget(self.send_btn)
        layout.addLayout(url_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Params")
        self.tabs.addTab(QWidget(), "Headers")
        self.tabs.addTab(QWidget(), "Body")
        self.tabs.addTab(QWidget(), "Auth")
        layout.addWidget(self.tabs)
