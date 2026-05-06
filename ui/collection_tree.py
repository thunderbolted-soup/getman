from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTreeWidget

class CollectionTreeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Collections"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Name")
        layout.addWidget(self.tree)
