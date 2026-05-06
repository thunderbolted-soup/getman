from PySide6.QtWidgets import (QMainWindow, QSplitter, QWidget, QVBoxLayout, 
                             QPushButton, QHBoxLayout, QTabWidget, QInputDialog)
from PySide6.QtCore import Qt
from ui.collection_tree import CollectionTreeWidget
from ui.history_panel import HistoryPanel
from ui.request_panel import RequestPanel
from ui.response_panel import ResponsePanel
from ui.log_viewer import LogViewer
from core.http_client import HttpClientThread
from storage.history import add_to_history
from core.collection import get_collections_list, load_collection, save_collection
from core.logger import get_logger

logger = get_logger()

class RequestTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        self.splitter = QSplitter(Qt.Vertical)
        self.request_panel = RequestPanel()
        self.response_panel = ResponsePanel()
        
        self.splitter.addWidget(self.request_panel)
        self.splitter.addWidget(self.response_panel)
        self.splitter.setSizes([400, 400])
        
        layout.addWidget(self.splitter)
        
        self.request_thread = None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Getman")
        self.resize(1200, 900)
        
        self.log_viewer = LogViewer()
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top bar
        top_bar = QHBoxLayout()
        self.new_tab_btn = QPushButton("+ New Tab")
        self.new_tab_btn.clicked.connect(self.add_new_tab)
        top_bar.addWidget(self.new_tab_btn)
        top_bar.addStretch()
        self.logs_btn = QPushButton("System Logs")
        self.logs_btn.clicked.connect(self.show_logs)
        top_bar.addWidget(self.logs_btn)
        main_layout.addLayout(top_bar)
        
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # Sidebar
        self.sidebar_splitter = QSplitter(Qt.Vertical)
        self.collection_tree = CollectionTreeWidget()
        self.history_panel = HistoryPanel()
        self.sidebar_splitter.addWidget(self.collection_tree)
        self.sidebar_splitter.addWidget(self.history_panel)
        
        # Request Tabs
        self.request_tabs = QTabWidget()
        self.request_tabs.setTabsClosable(True)
        self.request_tabs.tabCloseRequested.connect(self.close_tab)
        
        self.main_splitter.addWidget(self.sidebar_splitter)
        self.main_splitter.addWidget(self.request_tabs)
        self.main_splitter.setSizes([300, 900])
        
        main_layout.addWidget(self.main_splitter)
        
        # Initial Tab
        self.add_new_tab()
        
        # Global connections
        self.collection_tree.request_selected.connect(self.load_request)
        self.history_panel.request_selected.connect(self.load_request)
        
        logger.info("Getman UI Initialized with Tab Support")

    def add_new_tab(self):
        tab = RequestTab()
        index = self.request_tabs.addTab(tab, "New Request")
        self.request_tabs.setCurrentIndex(index)
        
        # Connect signals for the new tab
        tab.request_panel.send_requested.connect(lambda *args: self.on_send_request(tab, *args))
        tab.request_panel.save_requested.connect(lambda data: self.on_save_request(tab, data))

    def close_tab(self, index):
        if self.request_tabs.count() > 1:
            self.request_tabs.removeTab(index)

    def show_logs(self):
        self.log_viewer.show()
        self.log_viewer.raise_()

    def current_tab(self) -> RequestTab:
        return self.request_tabs.currentWidget()

    def load_request(self, data):
        tab = self.current_tab()
        if not tab:
            self.add_new_tab()
            tab = self.current_tab()
        tab.request_panel.set_request_data(data)
        self.request_tabs.setTabText(self.request_tabs.currentIndex(), f"{data.get('method', 'GET')} {data.get('url', 'Request')[:20]}")

    def on_send_request(self, tab, method, url, headers, body, params):
        logger.debug(f"Tab Sending: {method} {url}")
        tab.response_panel.status_label.setText("Sending...")
        tab.request_thread = HttpClientThread(method, url, headers, body, params)
        tab.request_thread.finished.connect(lambda res: self.on_request_finished(tab, res))
        tab.request_thread.error.connect(lambda err: self.on_request_error(tab, err))
        
        tab.request_panel.send_btn.setEnabled(False)
        tab.request_thread.start()

    def on_request_finished(self, tab, result):
        tab.request_panel.send_btn.setEnabled(True)
        tab.response_panel.set_response(result)
        
        history_entry = {
            "method": tab.request_thread.method,
            "url": tab.request_thread.url,
            "headers": tab.request_thread.headers,
            "params": tab.request_thread.params,
            "body": tab.request_thread.body,
            "response_status": result["status_code"],
            "response_time_ms": result["elapsed_ms"]
        }
        add_to_history(history_entry)
        self.history_panel.refresh()

    def on_request_error(self, tab, error_msg):
        tab.request_panel.send_btn.setEnabled(True)
        tab.response_panel.set_error(error_msg)

    def on_save_request(self, tab, data):
        collections = get_collections_list()
        if not collections:
            logger.warning("No collections found to save into")
            return
            
        col_name, ok = QInputDialog.getItem(self, "Save to Collection", "Select Collection:", collections, 0, False)
        if ok and col_name:
            col_data = load_collection(col_name)
            if col_data:
                req_name, ok = QInputDialog.getText(self, "Request Name", "Enter name for this request:")
                if ok and req_name:
                    new_item = {
                        "name": req_name,
                        "request": {
                            "method": data["method"],
                            "url": {"raw": data["url"]},
                            "header": [{"key": k, "value": v} for k, v in data["headers"].items()],
                            "body": {"mode": "raw", "raw": data["body"]} if data["body"] else {}
                        }
                    }
                    col_data.setdefault("item", []).append(new_item)
                    save_collection(col_name, col_data)
                    self.collection_tree.refresh()
                    logger.info(f"Saved request '{req_name}' to {col_name}")
