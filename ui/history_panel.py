from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout
from PySide6.QtCore import Signal, Qt
from storage.history import get_history, clear_history

class HistoryPanel(QWidget):
    request_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("History"))
        header_layout.addStretch()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.on_clear_clicked)
        header_layout.addWidget(self.clear_btn)
        layout.addLayout(header_layout)
        
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.on_item_clicked)
        layout.addWidget(self.list)
        
        self.refresh()

    def refresh(self):
        self.list.clear()
        history = get_history()
        for entry in history:
            status = entry.get('response_status', '-')
            # Simple list item text
            item_text = f"[{status}] {entry['method']} {entry['url']}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, entry)
            
            # Basic coloring based on status
            if isinstance(status, int):
                if 200 <= status < 300:
                    item.setForeground(Qt.darkGreen)
                elif status >= 400:
                    item.setForeground(Qt.red)
                    
            self.list.addItem(item)

    def on_item_clicked(self, item):
        data = item.data(Qt.UserRole)
        self.request_selected.emit(data)

    def on_clear_clicked(self):
        clear_history()
        self.refresh()

    def filter_history(self, text):
        text = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            match = text in item.text().lower()
            item.setHidden(not match)
