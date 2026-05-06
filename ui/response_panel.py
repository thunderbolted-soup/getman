import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                             QTabWidget, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView)
from PySide6.QtGui import QFont
from pygments import highlight
from pygments.lexers import JsonLexer, XmlLexer, HttpLexer, TextLexer
from pygments.formatters import HtmlFormatter

class ResponsePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # Status Bar
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: -")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.time_label = QLabel("Time: - ms")
        self.size_label = QLabel("Size: - B")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.time_label)
        status_layout.addWidget(self.size_label)
        layout.addLayout(status_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        
        # Body Tab
        self.body_edit = QTextEdit()
        self.body_edit.setReadOnly(True)
        self.body_edit.setFont(QFont("Courier New", 10))
        self.tabs.addTab(self.body_edit, "Body")
        
        # Headers Tab
        self.headers_table = QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.headers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabs.addTab(self.headers_table, "Headers")
        
        layout.addWidget(self.tabs)

    def set_response(self, response_data: dict):
        # Update labels
        status_code = response_data.get("status_code", "-")
        reason = response_data.get("reason_phrase", "")
        self.status_label.setText(f"Status: {status_code} {reason}")
        
        # Color status code
        if 200 <= status_code < 300:
            self.status_label.setStyleSheet("font-weight: bold; color: green;")
        elif 300 <= status_code < 400:
            self.status_label.setStyleSheet("font-weight: bold; color: orange;")
        else:
            self.status_label.setStyleSheet("font-weight: bold; color: red;")
            
        self.time_label.setText(f"Time: {response_data.get('elapsed_ms', '-')} ms")
        
        size = response_data.get("size", 0)
        if size > 1024:
            self.size_label.setText(f"Size: {size/1024:.2f} KB")
        else:
            self.size_label.setText(f"Size: {size} B")

        # Update Body with highlighting
        text = response_data.get("text", "")
        headers = response_data.get("headers", {})
        content_type = headers.get("Content-Type", "").lower()
        
        lexer = TextLexer()
        if "application/json" in content_type:
            lexer = JsonLexer()
            try:
                # Pretty print
                parsed = json.loads(text)
                text = json.dumps(parsed, indent=2)
            except:
                pass
        elif "application/xml" in content_type or "text/xml" in content_type:
            lexer = XmlLexer()
            
        formatter = HtmlFormatter(nowrap=False, style='friendly')
        highlighted = highlight(text, lexer, formatter)
        css = formatter.get_style_defs()
        
        # Simple HTML wrapper
        html = f"<html><head><style>{css}</style></head><body>{highlighted}</body></html>"
        self.body_edit.setHtml(html)

        # Update Headers
        self.headers_table.setRowCount(0)
        for key, value in headers.items():
            row = self.headers_table.rowCount()
            self.headers_table.insertRow(row)
            self.headers_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.headers_table.setItem(row, 1, QTableWidgetItem(str(value)))

    def set_error(self, error_msg: str):
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        self.body_edit.setPlainText(error_msg)
        self.time_label.setText("Time: - ms")
        self.size_label.setText("Size: - B")
        self.headers_table.setRowCount(0)
