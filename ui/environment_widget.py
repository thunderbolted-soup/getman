from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QPushButton, QLineEdit, QLabel, QInputDialog, QListWidgetItem, QDialog)
from PySide6.QtCore import Qt, Signal
from core.environment import get_all_environments, save_environments
from ui.shared_widgets import KeyValueTable

class EnvironmentManagerWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        
        # Left side: List of environments
        left_layout = QVBoxLayout()
        self.env_list = QListWidget()
        self.env_list.itemClicked.connect(self.on_env_selected)
        left_layout.addWidget(QLabel("Environments"))
        left_layout.addWidget(self.env_list)
        
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self.on_add_clicked)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.on_delete_clicked)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.del_btn)
        left_layout.addLayout(btn_layout)
        layout.addLayout(left_layout)
        
        # Right side: Variable editor
        self.edit_widget = QWidget()
        edit_layout = QVBoxLayout(self.edit_widget)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Environment Name")
        edit_layout.addWidget(QLabel("Name:"))
        edit_layout.addWidget(self.name_edit)
        
        self.var_table = KeyValueTable()
        edit_layout.addWidget(QLabel("Variables:"))
        edit_layout.addWidget(self.var_table)
        
        self.save_btn = QPushButton("Save Environment")
        self.save_btn.clicked.connect(self.on_save_clicked)
        edit_layout.addWidget(self.save_btn)
        
        layout.addWidget(self.edit_widget)
        self.edit_widget.setEnabled(False)
        
        self.refresh()

    def refresh(self):
        self.env_list.clear()
        for env in get_all_environments():
            item = QListWidgetItem(env["name"])
            item.setData(Qt.UserRole, env)
            self.env_list.addItem(item)

    def on_add_clicked(self):
        name, ok = QInputDialog.getText(self, "New Environment", "Enter name:")
        if ok and name:
            envs = get_all_environments()
            envs.append({"name": name, "values": {}})
            save_environments(envs)
            self.refresh()
            self.changed.emit()

    def on_env_selected(self, item):
        env = item.data(Qt.UserRole)
        self.name_edit.setText(env["name"])
        self.var_table.set_data(env.get("values", {}))
        self.edit_widget.setEnabled(True)

    def on_save_clicked(self):
        item = self.env_list.currentItem()
        if not item:
            return
            
        old_env = item.data(Qt.UserRole)
        new_name = self.name_edit.text()
        new_values = self.var_table.get_data()
        
        envs = get_all_environments()
        for env in envs:
            if env["name"] == old_env["name"]:
                env["name"] = new_name
                env["values"] = new_values
                break
                
        save_environments(envs)
        self.refresh()
        self.changed.emit()

    def on_delete_clicked(self):
        item = self.env_list.currentItem()
        if item:
            env_to_del = item.data(Qt.UserRole)
            envs = [e for e in get_all_environments() if e["name"] != env_to_del["name"]]
            save_environments(envs)
            self.edit_widget.setEnabled(False)
            self.refresh()
            self.changed.emit()
