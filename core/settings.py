"""Application settings (``data/settings.json``)."""
from typing import Any, Dict

from core.paths import data_path
from core.storage import load_json, save_json

DEFAULTS: Dict[str, Any] = {
    "theme": "dark",               # dark | light
    "layout": "vertical",          # response below (vertical) or beside (horizontal) the request
    "editor_font_size": 10,
    "verify_ssl": True,
    "follow_redirects": True,
    "request_timeout": 60,         # seconds, 0 = no timeout
    "proxy_mode": "system",        # system | none | custom
    "proxy_url": "",
    "max_history_size": 300,
    "max_response_mb": 50,
    "default_headers": [],         # [kv] added to every request
    "send_cookies": True,
}


class Settings:
    def __init__(self, path: str = None):
        self.path = path or data_path("settings.json")
        raw = load_json(self.path, {})
        self.data = dict(DEFAULTS)
        if isinstance(raw, dict):
            self.data.update({k: v for k, v in raw.items() if k in DEFAULTS})
            # Getman 1.x: proxy_url without proxy_mode, default headers as dict
            if raw.get("proxy_url") and "proxy_mode" not in raw:
                self.data["proxy_mode"] = "custom"
            if isinstance(self.data["default_headers"], dict):
                self.data["default_headers"] = [{"key": k, "value": v, "enabled": True}
                                                for k, v in self.data["default_headers"].items()]
        if self.data["theme"] not in ("dark", "light"):
            self.data["theme"] = "dark"

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, values: Dict[str, Any]):
        self.data.update(values)
        self.save()

    def save(self):
        save_json(self.path, self.data)
