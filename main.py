import sys
import os
from PySide6.QtWidgets import QApplication

# Ensure data directories exist on startup
from core.collection import ensure_collections_dir
from storage.store import ensure_dir

def setup_app():
    ensure_collections_dir()
    # Ensure other files/dirs if needed
    if not os.path.exists("data"):
        os.makedirs("data")

def main():
    setup_app()
    
    app = QApplication(sys.argv)
    app.setApplicationName("Getman - Postman Clone")
    
    # UI will be initialized in Phase 2
    print("Postman Clone Foundation Ready.")
    
    # sys.exit(app.exec())
    return 0

if __name__ == "__main__":
    sys.exit(main())
