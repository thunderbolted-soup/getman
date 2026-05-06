from typing import Dict, Any
from storage.store import load_json, save_json

SETTINGS_FILE = "data/settings.json"

def get_settings() -> Dict[str, Any]:
    """Returns the global application settings."""
    return load_json(SETTINGS_FILE, {
        "verify_ssl": True,
        "proxy_url": "",
        "request_timeout": 60,
        "max_history_size": 100,
        "default_headers": {},
        "theme": "dark"
    })

def save_settings(settings: Dict[str, Any]):
    """Saves the global application settings."""
    save_json(SETTINGS_FILE, settings)
