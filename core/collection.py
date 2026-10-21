"""Collections live one-per-file in ``data/collections/*.json``."""
import os
import re
from typing import Dict, List, Optional, Tuple

from core.logger import get_logger
from core.models import find_item, new_collection, normalize_collection
from core.paths import data_path
from core.storage import load_json, save_json

logger = get_logger()


def _safe_filename(name: str) -> str:
    safe = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip().replace(" ", "_")
    return safe[:60] or "collection"


class CollectionStore:
    def __init__(self, directory: str = None):
        self.directory = directory or data_path("collections")
        os.makedirs(self.directory, exist_ok=True)
        self.collections: List[dict] = []
        self._files: Dict[str, str] = {}
        self.load()

    def load(self):
        self.collections, self._files = [], {}
        for filename in sorted(os.listdir(self.directory)):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.directory, filename)
            raw = load_json(path)
            if not isinstance(raw, dict):
                logger.warning("Skipping unreadable collection file %s", filename)
                continue
            if "getman" not in raw:
                # Files from Getman 1.x were stored in Postman format.
                from core.importers import postman
                try:
                    raw = postman.parse_collection(raw)
                except Exception as e:  # noqa: BLE001 - keep loading the others
                    logger.warning("Cannot migrate %s: %s", filename, e)
                    continue
                col = normalize_collection(raw)
                self._files[col["id"]] = filename
                self.collections.append(col)
                self.save(col)
                logger.info("Migrated legacy collection %s", filename)
                continue
            col = normalize_collection(raw)
            if col["id"] in self._files:  # duplicated file -> give it a new identity
                from core.models import new_id
                col["id"] = new_id()
            self._files[col["id"]] = filename
            self.collections.append(col)
        self.collections.sort(key=lambda c: c["name"].lower())

    def get(self, col_id: str) -> Optional[dict]:
        for col in self.collections:
            if col["id"] == col_id:
                return col
        return None

    def _filename_for(self, col: dict) -> str:
        if col["id"] in self._files:
            return self._files[col["id"]]
        base = _safe_filename(col["name"])
        filename, i = f"{base}.json", 2
        taken = set(self._files.values())
        while filename in taken or os.path.exists(os.path.join(self.directory, filename)):
            filename = f"{base}_{i}.json"
            i += 1
        self._files[col["id"]] = filename
        return filename

    def save(self, col: dict):
        save_json(os.path.join(self.directory, self._filename_for(col)), col)

    def create(self, name: str) -> dict:
        col = new_collection(name)
        return self.add(col)

    def add(self, col: dict) -> dict:
        col = normalize_collection(col)
        while self.get(col["id"]):
            from core.models import new_id
            col["id"] = new_id()
        self.collections.append(col)
        self.collections.sort(key=lambda c: c["name"].lower())
        self.save(col)
        return col

    def delete(self, col_id: str):
        col = self.get(col_id)
        if not col:
            return
        self.collections.remove(col)
        filename = self._files.pop(col_id, None)
        if filename:
            try:
                os.remove(os.path.join(self.directory, filename))
            except OSError as e:
                logger.warning("Cannot delete %s: %s", filename, e)

    def find(self, item_id: str) -> Optional[Tuple[dict, dict, Tuple[dict, ...]]]:
        """Locates any folder/request: returns (collection, item, ancestors)."""
        for col in self.collections:
            found = find_item(col, item_id)
            if found:
                return col, found[0], found[1]
        return None

    def file_path(self, col_id: str) -> Optional[str]:
        filename = self._files.get(col_id)
        return os.path.join(self.directory, filename) if filename else None
