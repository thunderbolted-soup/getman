from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView)
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
