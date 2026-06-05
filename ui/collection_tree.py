from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTreeWidget, 
                             QTreeWidgetItem, QMenu, QFileDialog, QPushButton, QHBoxLayout, QInputDialog)
from PySide6.QtCore import Signal, Qt
from core.collection import (get_collections_list, load_collection, import_external_collection, 
                            delete_collection, create_new_collection)

class CollectionTreeWidget(QWidget):
    request_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Collections"))
        header_layout.addStretch()
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self.on_new_collection_clicked)
        self.import_btn = QPushButton("Import Postman")
        self.import_btn.clicked.connect(self.on_import_clicked)
        self.import_openapi_btn = QPushButton("Import OpenAPI")
        self.import_openapi_btn.clicked.connect(self.on_import_openapi_clicked)
        header_layout.addWidget(self.new_btn)
        header_layout.addWidget(self.import_btn)
        header_layout.addWidget(self.import_openapi_btn)
        layout.addLayout(header_layout)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.on_item_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        
        # Enable Drag and Drop
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.InternalMove)
        
        # Intercept dropEvent to save changes
        self.original_drop_event = self.tree.dropEvent
        self.tree.dropEvent = self.custom_drop_event
        
        layout.addWidget(self.tree)
        
        self.refresh()

    def custom_drop_event(self, event):
        self.original_drop_event(event)
        self.save_tree_to_collections()

    def save_tree_to_collections(self):
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            data = root.data(0, Qt.UserRole)
            if data and data["type"] == "collection":
                filename = data["filename"]
                orig_data = data.get("original_data", {})
                orig_data["item"] = self._build_items(root)
                from core.collection import save_collection
                save_collection(filename, orig_data)

    def _build_items(self, parent_item):
        items = []
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            user_data = child.data(0, Qt.UserRole)
            if not user_data: continue
            
            if user_data["type"] == "folder":
                items.append({
                    "name": child.text(0),
                    "item": self._build_items(child)
                })
            elif user_data["type"] == "request":
                items.append({
                    "name": user_data.get("name", "Unnamed"),
                    "request": user_data["data"]
                })
        return items

    def filter_tree(self, text):
        text = text.lower()
        def _filter(item):
            match = False
            if text in item.text(0).lower():
                match = True
            
            user_data = item.data(0, Qt.UserRole)
            if user_data and user_data["type"] == "request":
                req_data = user_data.get("data", {})
                url = req_data.get("url", "")
                if isinstance(url, dict): 
                    url = url.get("raw", "")
                if text in url.lower():
                    match = True
                    
            for i in range(item.childCount()):
                child = item.child(i)
                if _filter(child):
                    match = True
                    
            item.setHidden(not match and text != "")
            if match and text != "":
                item.setExpanded(True)
            return match
            
        for i in range(self.tree.topLevelItemCount()):
            _filter(self.tree.topLevelItem(i))

    def refresh(self):
        self.tree.clear()
        for filename in get_collections_list():
            data = load_collection(filename)
            if data:
                root = QTreeWidgetItem(self.tree)
                root.setText(0, data.get("info", {}).get("name", filename))
                root.setData(0, Qt.UserRole, {"type": "collection", "filename": filename, "original_data": data})
                root.setFlags(root.flags() & ~Qt.ItemIsDragEnabled) # Collections can't be dragged
                self._add_items(root, data.get("item", []))

    def _add_items(self, parent_item, items):
        for item in items:
            tree_item = QTreeWidgetItem(parent_item)
            name = item.get("name", "Unnamed")
            
            if "request" in item:
                # Request item
                method = item["request"].get("method", "GET")
                tree_item.setText(0, f"[{method}] {name}")
                tree_item.setData(0, Qt.UserRole, {"type": "request", "data": item["request"], "name": name})
                
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
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Collection", "", "JSON Files (*.json)")
        if file_path:
            import_external_collection(file_path)
            self.refresh()

    def on_import_openapi_clicked(self):
        from ui.openapi_import_dialog import OpenApiImportDialog
        dialog = OpenApiImportDialog(self)
        if dialog.exec():
            self.refresh()

    def on_new_collection_clicked(self):
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        if ok and name:
            create_new_collection(name)
            self.refresh()

    def on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        data = item.data(0, Qt.UserRole)
        menu = QMenu()
        
        if data["type"] == "collection":
            new_folder_action = menu.addAction("New Folder")
            new_folder_action.triggered.connect(lambda: self.add_new_folder(item))
            menu.addSeparator()
            delete_action = menu.addAction("Delete Collection")
            delete_action.triggered.connect(lambda: self.delete_collection_item(item))
            
        elif data["type"] == "folder":
            new_folder_action = menu.addAction("New Folder")
            new_folder_action.triggered.connect(lambda: self.add_new_folder(item))
            rename_action = menu.addAction("Rename")
            rename_action.triggered.connect(lambda: self.rename_item(item))
            menu.addSeparator()
            delete_action = menu.addAction("Delete Folder")
            delete_action.triggered.connect(lambda: self.delete_tree_item(item))
            
        elif data["type"] == "request":
            rename_action = menu.addAction("Rename")
            rename_action.triggered.connect(lambda: self.rename_item(item))
            duplicate_action = menu.addAction("Duplicate")
            duplicate_action.triggered.connect(lambda: self.duplicate_request(item))
            menu.addSeparator()
            delete_action = menu.addAction("Delete Request")
            delete_action.triggered.connect(lambda: self.delete_tree_item(item))
        
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_new_folder(self, parent_item):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            folder_item = QTreeWidgetItem(parent_item)
            folder_item.setText(0, name)
            folder_item.setData(0, Qt.UserRole, {"type": "folder"})
            parent_item.setExpanded(True)
            self.save_tree_to_collections()

    def rename_item(self, item):
        data = item.data(0, Qt.UserRole)
        current_name = data.get("name") if data["type"] == "request" else item.text(0)
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=current_name)
        if ok and new_name:
            if data["type"] == "request":
                data["name"] = new_name
                method = data["data"].get("method", "GET")
                item.setText(0, f"[{method}] {new_name}")
                item.setData(0, Qt.UserRole, data)
            else:
                item.setText(0, new_name)
            self.save_tree_to_collections()

    def duplicate_request(self, item):
        import copy
        data = item.data(0, Qt.UserRole)
        parent = item.parent()
        if parent and data["type"] == "request":
            new_data = copy.deepcopy(data)
            new_data["name"] = new_data.get("name", "Unnamed") + " (Copy)"
            
            new_item = QTreeWidgetItem(parent)
            method = new_data["data"].get("method", "GET")
            new_item.setText(0, f"[{method}] {new_data['name']}")
            new_item.setData(0, Qt.UserRole, new_data)
            
            # Re-apply color
            if method == "GET": new_item.setForeground(0, Qt.blue)
            elif method == "POST": new_item.setForeground(0, Qt.darkGreen)
            elif method == "DELETE": new_item.setForeground(0, Qt.red)
            elif method == "PUT": new_item.setForeground(0, Qt.darkYellow)
            
            self.save_tree_to_collections()

    def delete_tree_item(self, item):
        parent = item.parent()
        if parent:
            parent.removeChild(item)
            self.save_tree_to_collections()

    def delete_collection_item(self, item):
        data = item.data(0, Qt.UserRole)
        if data["type"] == "collection":
            delete_collection(data["filename"])
            self.refresh()
