import sys
import os
from PySide6.QtWidgets import QApplication

# Ensure data directories exist on startup
from core.collection import ensure_collections_dir
from storage.store import ensure_dir

from ui.main_window import MainWindow

def setup_app():
    ensure_collections_dir()
    if not os.path.exists("data"):
        os.makedirs("data")

def main():
    setup_app()
    
    app = QApplication(sys.argv)
    app.setApplicationName("Getman - Postman Clone")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    sys.exit(main())
