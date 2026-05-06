from PySide6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
from ui.collection_tree import CollectionTreeWidget
from ui.history_panel import HistoryPanel
from ui.request_panel import RequestPanel
from ui.response_panel import ResponsePanel
from ui.log_viewer import LogViewer
from core.http_client import HttpClientThread
from storage.history import add_to_history
from core.logger import get_logger

logger = get_logger()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Getman")
        self.resize(1200, 800)
        
        self.log_viewer = LogViewer()
        
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top bar for global actions
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.logs_btn = QPushButton("System Logs")
        self.logs_btn.clicked.connect(self.show_logs)
        top_bar.addWidget(self.logs_btn)
        main_layout.addLayout(top_bar)
        
        # Main Splitter (Left Sidebar | Right Content)
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # Left Sidebar Splitter (Collections | History)
        self.sidebar_splitter = QSplitter(Qt.Vertical)
        self.collection_tree = CollectionTreeWidget()
        self.history_panel = HistoryPanel()
        self.sidebar_splitter.addWidget(self.collection_tree)
        self.sidebar_splitter.addWidget(self.history_panel)
        
        # Right Content Splitter (Request | Response)
        self.content_splitter = QSplitter(Qt.Vertical)
        self.request_panel = RequestPanel()
        self.response_panel = ResponsePanel()
        self.content_splitter.addWidget(self.request_panel)
        self.content_splitter.addWidget(self.response_panel)
        
        self.main_splitter.addWidget(self.sidebar_splitter)
        self.main_splitter.addWidget(self.content_splitter)
        
        # Set initial sizes (Sidebar 25%, Content 75%)
        self.main_splitter.setSizes([300, 900])
        # Request 40%, Response 60%
        self.content_splitter.setSizes([300, 500])
        
        main_layout.addWidget(self.main_splitter)

        # Connections
        self.request_panel.send_requested.connect(self.on_send_request)
        self.collection_tree.request_selected.connect(self.request_panel.set_request_data)
        self.history_panel.request_selected.connect(self.request_panel.set_request_data)
        
        logger.info("Getman UI Initialized")

    def show_logs(self):
        self.log_viewer.show()
        self.log_viewer.raise_()

    def on_send_request(self, method, url, headers, body, params):
        logger.debug(f"UI Triggered Send: {method} {url}")
        self.response_panel.status_label.setText("Sending...")
        self.request_thread = HttpClientThread(method, url, headers, body, params)
        self.request_thread.finished.connect(self.on_request_finished)
        self.request_thread.error.connect(self.on_request_error)
        
        self.request_panel.send_btn.setEnabled(False)
        self.request_thread.start()

    def on_request_finished(self, result):
        self.request_panel.send_btn.setEnabled(True)
        self.response_panel.set_response(result)
        
        # Save to history
        history_entry = {
            "method": self.request_thread.method,
            "url": self.request_thread.url,
            "headers": self.request_thread.headers,
            "params": self.request_thread.params,
            "body": self.request_thread.body,
            "response_status": result["status_code"],
            "response_time_ms": result["elapsed_ms"]
        }
        add_to_history(history_entry)
        self.history_panel.refresh()

    def on_request_error(self, error_msg):
        self.request_panel.send_btn.setEnabled(True)
        self.response_panel.set_error(error_msg)
