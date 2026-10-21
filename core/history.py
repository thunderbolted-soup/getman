"""Request history (``data/history.json``), newest first."""
import copy
import time
from typing import List, Optional

from core.models import new_id, normalize_request
from core.paths import data_path
from core.storage import load_json, save_json

MAX_BODY_IN_HISTORY = 64 * 1024


class HistoryStore:
    def __init__(self, path: str = None, limit: int = 300):
        self.path = path or data_path("history.json")
        self.limit = limit
        self.entries: List[dict] = []
        self.load()

    def load(self):
        raw = load_json(self.path, [])
        self.entries = []
        for e in raw if isinstance(raw, list) else []:
            if not isinstance(e, dict):
                continue
            if "request" not in e:  # Getman 1.x entry
                headers = e.get("headers") or {}
                req = {"method": e.get("method"), "url": e.get("url"),
                       "headers": [{"key": k, "value": v} for k, v in headers.items()]
                       if isinstance(headers, dict) else []}
                if isinstance(e.get("body"), str) and e["body"]:
                    req["body"] = {"mode": "text", "text": e["body"]}
                e = {"id": e.get("id") or new_id(), "ts": 0, "request": req,
                     "status": e.get("response_status"), "elapsed_ms": e.get("response_time_ms")}
            e["request"] = normalize_request(e.get("request"))
            self.entries.append(e)

    def save(self):
        save_json(self.path, self.entries, compact=True)

    def add(self, request: dict, status: Optional[int], elapsed_ms: Optional[int],
            size: Optional[int] = None, error: str = None) -> dict:
        req = copy.deepcopy(request)
        if len(req["body"].get("text", "")) > MAX_BODY_IN_HISTORY:
            req["body"]["text"] = req["body"]["text"][:MAX_BODY_IN_HISTORY]
        entry = {"id": new_id(), "ts": time.time(), "request": req, "status": status,
                 "elapsed_ms": elapsed_ms, "size": size, "error": error}
        self.entries.insert(0, entry)
        del self.entries[max(self.limit, 0):]
        self.save()
        return entry

    def remove(self, entry_id: str):
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        self.save()

    def clear(self):
        self.entries = []
        self.save()

    def set_limit(self, limit: int):
        self.limit = limit
        if len(self.entries) > limit:
            del self.entries[limit:]
            self.save()
