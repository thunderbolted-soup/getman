from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget

class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("History"))
        self.list = QListWidget()
        layout.addWidget(self.list)
