from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QLabel
from core.logger import get_log_signal

class LogViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Getman System Logs")
        self.resize(800, 400)
        
        layout = QVBoxLayout(self)
        
        header = QHBoxLayout()
        header.addWidget(QLabel("Application Logs:"))
        header.addStretch()
        self.clear_btn = QPushButton("Clear UI")
        self.clear_btn.clicked.connect(self.on_clear)
        header.addWidget(self.clear_btn)
        layout.addLayout(header)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New';")
        layout.addWidget(self.log_output)
        
        get_log_signal().connect(self.append_log)

    def append_log(self, message):
        self.log_output.append(message)
        # Auto scroll to bottom
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def on_clear(self):
        self.log_output.clear()
