from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTreeWidget, 
                             QTreeWidgetItem, QMenu, QFileDialog, QPushButton, QHBoxLayout)
from PySide6.QtCore import Signal, Qt
from core.collection import get_collections_list, load_collection, import_postman_collection, delete_collection

class CollectionTreeWidget(QWidget):
    request_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Collections"))
        header_layout.addStretch()
        self.import_btn = QPushButton("Import")
        self.import_btn.clicked.connect(self.on_import_clicked)
        header_layout.addWidget(self.import_btn)
        layout.addLayout(header_layout)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.on_item_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        layout.addWidget(self.tree)
        
        self.refresh()

    def refresh(self):
        self.tree.clear()
        for filename in get_collections_list():
            data = load_collection(filename)
            if data:
                root = QTreeWidgetItem(self.tree)
                root.setText(0, data.get("info", {}).get("name", filename))
                root.setData(0, Qt.UserRole, {"type": "collection", "filename": filename})
                self._add_items(root, data.get("item", []))

    def _add_items(self, parent_item, items):
        for item in items:
            tree_item = QTreeWidgetItem(parent_item)
            name = item.get("name", "Unnamed")
            
            if "request" in item:
                # Request item
                method = item["request"].get("method", "GET")
                tree_item.setText(0, f"[{method}] {name}")
                tree_item.setData(0, Qt.UserRole, {"type": "request", "data": item["request"]})
                
                # Simple color coding for methods
                if method == "GET": tree_item.setForeground(0, Qt.blue)
                elif method == "POST": tree_item.setForeground(0, Qt.darkGreen)
                elif method == "DELETE": tree_item.setForeground(0, Qt.red)
                elif method == "PUT": tree_item.setForeground(0, Qt.darkYellow)
            else:
                # Folder item
                tree_item.setText(0, name)
                tree_item.setData(0, Qt.UserRole, {"type": "folder"})
                self._add_items(tree_item, item.get("item", []))

    def on_item_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data and data["type"] == "request":
            self.request_selected.emit(data["data"])

    def on_import_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Postman Collection", "", "JSON Files (*.json)")
        if file_path:
            import_postman_collection(file_path)
            self.refresh()

    def on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        data = item.data(0, Qt.UserRole)
        menu = QMenu()
        
        if data["type"] == "collection":
            delete_action = menu.addAction("Delete Collection")
            delete_action.triggered.connect(lambda: self.delete_collection_item(item))
        
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def delete_collection_item(self, item):
        data = item.data(0, Qt.UserRole)
        if data["type"] == "collection":
            delete_collection(data["filename"])
            self.refresh()
