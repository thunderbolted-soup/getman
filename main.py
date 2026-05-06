import sys
import os
from PySide6.QtWidgets import QApplication

# Ensure data directories exist on startup
from core.collection import ensure_collections_dir
from storage.store import ensure_dir

from ui.main_window import MainWindow

from core.logger import get_logger

logger = get_logger()

def setup_app():
    ensure_collections_dir()
    if not os.path.exists("data"):
        os.makedirs("data")
    logger.info("Application setup complete")

def main():
    setup_app()
    
    app = QApplication(sys.argv)
    app.setApplicationName("Getman")
    
    window = MainWindow()
    window.show()
    
    logger.info("Starting Getman event loop")
    sys.exit(app.exec())

if __name__ == "__main__":
    sys.exit(main())
