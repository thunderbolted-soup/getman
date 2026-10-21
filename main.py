import gc
import os
import sys


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Getman")
    app.setOrganizationName("Getman")

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    # Startup objects live for the whole session: move them out of the GC's way.
    gc.collect()
    gc.freeze()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
