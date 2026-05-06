from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QTabWidget, QTextEdit

class ResponsePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # Status Bar
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: -")
        self.time_label = QLabel("Time: - ms")
        self.size_label = QLabel("Size: - B")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.time_label)
        status_layout.addWidget(self.size_label)
        layout.addLayout(status_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        self.body_edit = QTextEdit()
        self.body_edit.setReadOnly(True)
        self.tabs.addTab(self.body_edit, "Body")
        self.tabs.addTab(QWidget(), "Headers")
        layout.addWidget(self.tabs)
