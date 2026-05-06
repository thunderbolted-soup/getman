from PySide6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout
from PySide6.QtCore import Qt
from ui.collection_tree import CollectionTreeWidget
from ui.history_panel import HistoryPanel
from ui.request_panel import RequestPanel
from ui.response_panel import ResponsePanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Getman - Postman Clone")
        self.resize(1200, 800)
        
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
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
