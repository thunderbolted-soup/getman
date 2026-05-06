import logging
import os
from PySide6.QtCore import QObject, Signal

class SignallingHandler(logging.Handler):
    """Custom logging handler that emits a signal for each log record."""
    def __init__(self, signal: Signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class Logger(QObject):
    log_signal = Signal(str)
    
    _instance = None
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("Getman")
        self.logger.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S')
        
        # Signalling Handler
        self.handler = SignallingHandler(self.log_signal)
        self.handler.setFormatter(formatter)
        self.logger.addHandler(self.handler)
        
        # File Handler (optional but good for persistence)
        if not os.path.exists("data"):
            os.makedirs("data")
        file_handler = logging.FileHandler("data/app.log")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

def get_logger():
    return Logger.get_instance().logger

def get_log_signal():
    return Logger.get_instance().log_signal
