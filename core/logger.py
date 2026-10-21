"""File logger (``data/app.log``). The file is trimmed at startup instead of
using logging.handlers, which would pull in socket/pickle/queue (~2 MB)."""
import logging
import os

MAX_LOG_BYTES = 512 * 1024
_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("getman")
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        try:
            from core.paths import data_path
            path = data_path("app.log")
            if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
                with open(path, "rb") as f:
                    f.seek(-MAX_LOG_BYTES // 2, os.SEEK_END)
                    tail = f.read()
                with open(path, "wb") as f:
                    f.write(tail[tail.find(b"\n") + 1:])
            handler = logging.FileHandler(path, encoding="utf-8")
        except OSError:
            handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        _logger.addHandler(handler)
    return _logger
