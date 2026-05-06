from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog)
from PySide6.QtCore import Qt

class KeyValueTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["", "Key", "Value"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 30)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.add_empty_row()
        self.itemChanged.connect(self.on_item_changed)

    def add_empty_row(self):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)
        
        check_item = QTableWidgetItem()
        check_item.setCheckState(Qt.Checked)
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        self.setItem(row, 0, check_item)
        
        self.setItem(row, 1, QTableWidgetItem(""))
        self.setItem(row, 2, QTableWidgetItem(""))
        self.blockSignals(False)

    def on_item_changed(self, item):
        if item.row() == self.rowCount() - 1:
            key_item = self.item(item.row(), 1)
            if key_item and key_item.text():
                self.add_empty_row()

    def get_data(self) -> dict:
        data = {}
        for row in range(self.rowCount()):
            check_item = self.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                key_item = self.item(row, 1)
                val_item = self.item(row, 2)
                if key_item and key_item.text():
                    data[key_item.text()] = val_item.text() if val_item else ""
        return data

    def set_data(self, data: dict):
        self.setRowCount(0)
        for key, value in data.items():
            row = self.rowCount()
            self.insertRow(row)
            check_item = QTableWidgetItem()
            check_item.setCheckState(Qt.Checked)
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            self.setItem(row, 0, check_item)
            self.setItem(row, 1, QTableWidgetItem(str(key)))
            self.setItem(row, 2, QTableWidgetItem(str(value)))
        self.add_empty_row()

class FormDataTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["", "Key", "Type", "Value"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 30)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(2, 80)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.add_empty_row()
        self.itemChanged.connect(self.on_item_changed)

    def add_empty_row(self):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)
        
        check_item = QTableWidgetItem()
        check_item.setCheckState(Qt.Checked)
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        self.setItem(row, 0, check_item)
        
        self.setItem(row, 1, QTableWidgetItem(""))
        
        type_combo = QComboBox()
        type_combo.addItems(["Text", "File"])
        type_combo.currentTextChanged.connect(self.on_type_changed)
        self.setCellWidget(row, 2, type_combo)
        
        self.setItem(row, 3, QTableWidgetItem(""))
        self.blockSignals(False)

    def on_type_changed(self, type_text):
        combo = self.sender()
        if not combo: return
        row = -1
        for r in range(self.rowCount()):
            if self.cellWidget(r, 2) == combo:
                row = r
                break
        if row == -1: return

        if type_text == "File":
            file_widget = QWidget()
            layout = QHBoxLayout(file_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            
            line_edit = QLineEdit()
            line_edit.setReadOnly(True)
            
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(lambda: self.browse_file(line_edit))
            
            layout.addWidget(line_edit)
            layout.addWidget(browse_btn)
            
            self.setCellWidget(row, 3, file_widget)
        else:
            self.removeCellWidget(row, 3)
            self.setItem(row, 3, QTableWidgetItem(""))

    def browse_file(self, line_edit):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if file_path:
            line_edit.setText(file_path)

    def on_item_changed(self, item):
        if item.row() == self.rowCount() - 1 and item.column() == 1:
            key_item = self.item(item.row(), 1)
            if key_item and key_item.text():
                self.add_empty_row()

    def get_data(self) -> list:
        data = []
        for row in range(self.rowCount()):
            check_item = self.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                key_item = self.item(row, 1)
                if key_item and key_item.text():
                    type_combo = self.cellWidget(row, 2)
                    item_type = type_combo.currentText() if type_combo else "Text"
                    
                    value = ""
                    if item_type == "File":
                        file_widget = self.cellWidget(row, 3)
                        if file_widget:
                            line_edit = file_widget.findChild(QLineEdit)
                            if line_edit:
                                value = line_edit.text()
                    else:
                        val_item = self.item(row, 3)
                        value = val_item.text() if val_item else ""
                        
                    data.append({"key": key_item.text(), "type": item_type, "value": value})
        return data

    def set_data(self, data):
        self.setRowCount(0)
        
        # Backward compatibility if data is dict
        if isinstance(data, dict):
            data = [{"key": k, "type": "Text", "value": str(v)} for k, v in data.items()]
            
        if not isinstance(data, list):
            data = []
            
        for item in data:
            row = self.rowCount()
            self.insertRow(row)
            
            check_item = QTableWidgetItem()
            check_item.setCheckState(Qt.Checked)
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            self.setItem(row, 0, check_item)
            
            self.setItem(row, 1, QTableWidgetItem(str(item.get("key", ""))))
            
            type_combo = QComboBox()
            type_combo.addItems(["Text", "File"])
            item_type = item.get("type", "Text")
            type_combo.setCurrentText(item_type)
            type_combo.currentTextChanged.connect(self.on_type_changed)
            self.setCellWidget(row, 2, type_combo)
            
            if item_type == "File":
                file_widget = QWidget()
                layout = QHBoxLayout(file_widget)
                layout.setContentsMargins(0, 0, 0, 0)
                line_edit = QLineEdit()
                line_edit.setReadOnly(True)
                line_edit.setText(str(item.get("value", "")))
                browse_btn = QPushButton("Browse...")
                browse_btn.clicked.connect(lambda le=line_edit: self.browse_file(le))
                layout.addWidget(line_edit)
                layout.addWidget(browse_btn)
                self.setCellWidget(row, 3, file_widget)
            else:
                self.setItem(row, 3, QTableWidgetItem(str(item.get("value", ""))))
                
        self.add_empty_row()
