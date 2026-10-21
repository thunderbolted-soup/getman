"""Location of the local data directory (collections, environments, history...)."""
import os
import sys

_data_dir = None


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Getman")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Getman")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "getman")


def data_dir() -> str:
    """Portable mode first: ``data/`` next to the app. Falls back to the user
    profile when the app folder is read-only (e.g. installed in Program Files)."""
    global _data_dir
    if _data_dir is None:
        path = os.environ.get("GETMAN_DATA_DIR")
        if not path:
            path = os.path.join(app_dir(), "data")
            try:
                os.makedirs(path, exist_ok=True)
                if not os.access(path, os.W_OK):
                    raise PermissionError(path)
            except OSError:
                path = _user_data_dir()
        os.makedirs(path, exist_ok=True)
        _data_dir = path
    return _data_dir


def set_data_dir(path: str):
    global _data_dir
    os.makedirs(path, exist_ok=True)
    _data_dir = path


def data_path(*parts: str) -> str:
    return os.path.join(data_dir(), *parts)
