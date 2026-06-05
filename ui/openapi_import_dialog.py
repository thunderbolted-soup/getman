import os
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTreeWidget, QTreeWidgetItem, QCheckBox,
    QLineEdit, QGroupBox, QMessageBox, QProgressDialog, QWidget,
    QTabWidget
)
from PySide6.QtCore import Qt

from core.logger import get_logger

logger = get_logger()


class OpenApiImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import OpenAPI / Swagger Spec")
        self.resize(700, 550)

        self.spec = None
        self.source_path = ""
        self.endpoints = []

        layout = QVBoxLayout(self)

        # File selection
        file_layout = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("Select OpenAPI spec file (JSON/YAML)...")
        self.file_path_edit.setReadOnly(True)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.on_browse)
        file_layout.addWidget(self.file_path_edit)
        file_layout.addWidget(self.browse_btn)
        layout.addLayout(file_layout)

        # Endpoint tree
        layout.addWidget(QLabel("Select endpoints to import:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("QTreeWidget { background-color: #3c3f41; color: #fff; }")
        layout.addWidget(self.tree)

        # Selection buttons
        sel_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.on_select_all)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.on_deselect_all)
        sel_layout.addWidget(self.select_all_btn)
        sel_layout.addWidget(self.deselect_all_btn)
        sel_layout.addStretch()
        layout.addLayout(sel_layout)

        # Options group
        options_group = QGroupBox("Import Options")
        options_layout = QVBoxLayout(options_group)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Collection name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Auto from spec title")
        name_layout.addWidget(self.name_edit)
        options_layout.addLayout(name_layout)

        self.create_env_cb = QCheckBox("Create environment from server variables")
        self.create_env_cb.setChecked(True)
        options_layout.addWidget(self.create_env_cb)

        self.import_auth_cb = QCheckBox("Import auth profiles (API Key, Bearer, Basic, OAuth2)")
        self.import_auth_cb.setChecked(True)
        options_layout.addWidget(self.import_auth_cb)

        layout.addWidget(options_group)

        # Import button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.import_btn = QPushButton("Import")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self.on_import)
        self.import_btn.setStyleSheet(
            "QPushButton { background-color: #2d7d46; color: white; padding: 6px 20px; }"
        )
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def on_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open OpenAPI Spec", "",
            "OpenAPI Files (*.json *.yaml *.yml);;All Files (*.*)"
        )
        if file_path:
            self.load_spec(file_path)

    def load_spec(self, file_path: str):
        from core.openapi_parser import load_openapi_spec, get_available_endpoints

        self.source_path = file_path
        self.spec = load_openapi_spec(file_path)

        if not self.spec:
            QMessageBox.warning(
                self,
                "Parse Error",
                f"Could not parse the OpenAPI spec:\n{file_path}\n"
                "Make sure it's a valid OpenAPI 2, 3.0, or 3.1 file."
            )
            return

        self.endpoints = get_available_endpoints(self.spec)
        self.file_path_edit.setText(os.path.basename(file_path))
        self.import_btn.setEnabled(True)

        spec_title = self.spec.get("info", {}).get("title", "")
        if spec_title and not self.name_edit.text():
            self.name_edit.setText(spec_title)

        self.populate_tree()

    def populate_tree(self):
        self.tree.clear()

        tags: Dict[str, list] = {}
        for ep in self.endpoints:
            for tag in ep.get("tags", ["General"]):
                tags.setdefault(tag, []).append(ep)

        for tag_name in sorted(tags.keys()):
            tag_item = QTreeWidgetItem(self.tree)
            tag_item.setText(0, f"{tag_name} ({len(tags[tag_name])} endpoints)")
            tag_item.setFlags(tag_item.flags() | Qt.ItemIsUserCheckable)
            tag_item.setData(0, Qt.UserRole, {"type": "tag", "name": tag_name})
            tag_item.setCheckState(0, Qt.Checked)
            tag_item.setExpanded(True)

            for ep in tags[tag_name]:
                ep_item = QTreeWidgetItem(tag_item)
                summary = ep.get("summary", "")
                label = f"[{ep['method']}] {ep['path']}"
                if summary:
                    label += f"  —  {summary}"
                ep_item.setText(0, label)
                ep_item.setData(0, Qt.UserRole, {"type": "endpoint", "data": ep})
                ep_item.setCheckState(0, Qt.Checked)

        self.tree.itemChanged.connect(self.on_item_changed)

    def on_item_changed(self, item, column):
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        if data.get("type") == "tag":
            state = item.checkState(0)
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, state)

    def on_select_all(self):
        self._set_all_checks(Qt.Checked)

    def on_deselect_all(self):
        self._set_all_checks(Qt.Unchecked)

    def _set_all_checks(self, state):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setCheckState(0, state)

    def get_selected_endpoints(self) -> List[Dict[str, Any]]:
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            tag_item = self.tree.topLevelItem(i)
            for j in range(tag_item.childCount()):
                ep_item = tag_item.child(j)
                if ep_item.checkState(0) == Qt.Checked:
                    data = ep_item.data(0, Qt.UserRole)
                    if data and data.get("type") == "endpoint":
                        selected.append(data["data"])
        return selected

    def on_import(self):
        from core.openapi_parser import convert_to_collection, filter_collection_by_endpoints
        from core.collection import save_openapi_collection

        selected = self.get_selected_endpoints()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Select at least one endpoint to import.")
            return

        collection_name = self.name_edit.text().strip() or ""

        progress = QProgressDialog("Importing OpenAPI spec...", "", 0, 0, self)
        progress.setWindowTitle("Importing")
        progress.setCancelButton(None)
        progress.show()
        QWidget.gui_repaint(progress)

        try:
            collection, env_vars, auth_profiles = convert_to_collection(self.spec)
            collection = filter_collection_by_endpoints(collection, selected)

            filename, env, count = save_openapi_collection(
                collection=collection,
                env_vars=env_vars,
                auth_profiles=auth_profiles,
                collection_name=collection_name,
                create_env=self.create_env_cb.isChecked(),
                import_auth=self.import_auth_cb.isChecked(),
            )

            progress.close()

            if filename:
                msg_parts = [f"Imported {count} endpoints as collection '{collection_name or filename}'."]
                if env:
                    msg_parts.append(f"\nEnvironment '{env['name']}' created with {len(env['values'])} variables.")
                QMessageBox.information(self, "Import Successful", "\n".join(msg_parts))
                self.accept()
            else:
                QMessageBox.critical(self, "Import Failed", "Failed to import the OpenAPI spec.")
        except Exception as e:
            progress.close()
            logger.error(f"OpenAPI import failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Import Error", f"Import failed:\n{str(e)}")
