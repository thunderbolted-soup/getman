from PySide6.QtWidgets import (QMainWindow, QSplitter, QWidget, QVBoxLayout, 
                             QPushButton, QHBoxLayout, QTabWidget, QInputDialog, QMessageBox, QToolButton)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut, QKeySequence
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
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #555; height: 3px; } QSplitter::handle:hover { background-color: #888; }")
        
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
        top_bar.addStretch()
        
        self.hotkeys_btn = QPushButton("Hotkeys")
        self.hotkeys_btn.clicked.connect(self.show_hotkeys)
        top_bar.addWidget(self.hotkeys_btn)
        
        self.import_curl_btn = QPushButton("Import cURL")
        self.import_curl_btn.clicked.connect(self.import_curl)
        top_bar.addWidget(self.import_curl_btn)
        
        self.logs_btn = QPushButton("System Logs")
        self.logs_btn.clicked.connect(self.show_logs)
        top_bar.addWidget(self.logs_btn)
        main_layout.addLayout(top_bar)
        
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: #555; width: 3px; } QSplitter::handle:hover { background-color: #888; }")
        
        # Sidebar
        self.sidebar_splitter = QSplitter(Qt.Vertical)
        self.sidebar_splitter.setStyleSheet("QSplitter::handle { background-color: #555; height: 3px; } QSplitter::handle:hover { background-color: #888; }")
        
        self.collection_tree = CollectionTreeWidget()
        self.history_panel = HistoryPanel()
        self.sidebar_splitter.addWidget(self.collection_tree)
        self.sidebar_splitter.addWidget(self.history_panel)
        
        # Request Tabs
        self.request_tabs = QTabWidget()
        self.request_tabs.setTabsClosable(True)
        self.request_tabs.tabCloseRequested.connect(self.close_tab)
        self.request_tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)
        
        self.new_tab_btn = QToolButton()
        self.new_tab_btn.setText("+")
        self.new_tab_btn.clicked.connect(self.add_new_tab)
        self.request_tabs.setCornerWidget(self.new_tab_btn, Qt.TopRightCorner)
        
        self.main_splitter.addWidget(self.sidebar_splitter)
        self.main_splitter.addWidget(self.request_tabs)
        self.main_splitter.setSizes([300, 900])
        
        main_layout.addWidget(self.main_splitter)
        
        # Initial Tab
        self.add_new_tab()
        
        # Global connections
        self.collection_tree.request_selected.connect(self.load_request)
        self.history_panel.request_selected.connect(self.load_request_new_tab)
        
        # Global Hotkeys
        self.setup_hotkeys()
        
        logger.info("Getman UI Initialized with Hotkeys and Improved UX")

    def setup_hotkeys(self):
        # New Tab: Ctrl+T (Cmd+T on Mac)
        self.new_tab_shortcut = QShortcut(QKeySequence(QKeySequence.AddTab), self)
        self.new_tab_shortcut.activated.connect(self.add_new_tab)
        
        # Close Tab: Ctrl+W (Cmd+W on Mac)
        self.close_tab_shortcut = QShortcut(QKeySequence(QKeySequence.Close), self)
        self.close_tab_shortcut.activated.connect(lambda: self.close_tab(self.request_tabs.currentIndex()))
        
        # Send Request: Ctrl+Enter (Cmd+Enter on Mac)
        # Using custom sequence since there's no standard for "Send"
        self.send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.send_shortcut.activated.connect(self.trigger_current_send)
        
        # Save Request: Ctrl+S (Cmd+S on Mac)
        self.save_shortcut = QShortcut(QKeySequence(QKeySequence.Save), self)
        self.save_shortcut.activated.connect(self.trigger_current_save)

    def trigger_current_send(self):
        tab = self.current_tab()
        if tab:
            tab.request_panel.on_send_clicked()

    def trigger_current_save(self):
        tab = self.current_tab()
        if tab:
            tab.request_panel.on_save_clicked()

    def show_hotkeys(self):
        hotkeys_text = (
            "<b>Global Hotkeys:</b><br><br>"
            "Ctrl+T : New Tab<br>"
            "Ctrl+W : Close Tab<br>"
            "Ctrl+S : Save Request<br>"
            "Ctrl+Enter : Send Request<br><br>"
            "<i>(On macOS, use Command instead of Ctrl)</i>"
        )
        QMessageBox.information(self, "Getman Hotkeys", hotkeys_text)

    def closeEvent(self, event):
        self.log_viewer.close()
        super().closeEvent(event)

    def import_curl(self):
        curl_text, ok = QInputDialog.getMultiLineText(self, "Import cURL", "Paste cURL command here:")
        if ok and curl_text:
            try:
                import shlex
                parts = shlex.split(curl_text)
                if not parts or parts[0] != "curl":
                    raise ValueError("Not a valid cURL command")
                
                url = ""
                method = "GET"
                headers = {}
                data = ""
                
                i = 1
                while i < len(parts):
                    p = parts[i]
                    if p in ("-X", "--request") and i + 1 < len(parts):
                        method = parts[i+1].upper()
                        i += 1
                    elif p in ("-H", "--header") and i + 1 < len(parts):
                        h = parts[i+1]
                        if ":" in h:
                            k, v = h.split(":", 1)
                            headers[k.strip()] = v.strip()
                        i += 1
                    elif p in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode") and i + 1 < len(parts):
                        data = parts[i+1]
                        if method == "GET": method = "POST"
                        i += 1
                    elif p in ("-u", "--user", "-A", "--user-agent", "-e", "--referer", "-o", "--output", "-F", "--form", "-b", "--cookie", "-c", "--cookie-jar", "--url") and i + 1 < len(parts):
                        # Skip flags that take an argument
                        i += 1
                    elif p.startswith("--url="):
                        if not url:
                            url = p.split("=", 1)[1]
                    elif not p.startswith("-"):
                        # First positional argument that isn't a flag or an argument to a recognized flag is the URL
                        if not url:
                            url = p
                    i += 1
                
                if not url:
                    raise ValueError("No URL found in cURL command")
                    
                req_data = {"method": method, "url": url, "headers": headers, "body": {"mode": "raw", "raw": data} if data else ""}
                self.load_request_new_tab(req_data)
                logger.info("Imported cURL command")
            except Exception as e:
                QMessageBox.warning(self, "Import Error", f"Failed to parse cURL: {str(e)}")
                logger.error(f"cURL import failed: {str(e)}")

    def rename_tab(self, index):
        if index >= 0:
            old_name = self.request_tabs.tabText(index)
            new_name, ok = QInputDialog.getText(self, "Rename Tab", "Enter new name:", text=old_name)
            if ok and new_name:
                self.request_tabs.setTabText(index, new_name)

    def add_new_tab(self):
        tab = RequestTab()
        index = self.request_tabs.addTab(tab, "New Request")
        self.request_tabs.setCurrentIndex(index)
        
        # Connect signals for the new tab
        tab.request_panel.send_requested.connect(lambda *args: self.on_send_request(tab, *args))
        tab.request_panel.save_requested.connect(lambda data: self.on_save_request(tab, data))
        return tab

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
            tab = self.add_new_tab()
        tab.request_panel.set_request_data(data)
        self.request_tabs.setTabText(self.request_tabs.currentIndex(), f"{data.get('method', 'GET')} {data.get('url', 'Request')[:20]}")

    def load_request_new_tab(self, data):
        tab = self.add_new_tab()
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
            msg = "No collections found to save into. Please create or import one first."
            logger.warning(msg)
            QMessageBox.warning(self, "Save Error", msg)
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
                    QMessageBox.information(self, "Save Success", f"Request '{req_name}' saved to collection '{col_name}'.")
                else:
                    logger.debug("Save cancelled: No request name provided.")
            else:
                msg = f"Failed to load collection '{col_name}'."
                logger.error(msg)
                QMessageBox.critical(self, "Save Error", msg)
        else:
            logger.debug("Save cancelled: No collection selected.")
