"""Application-wide state shared by all widgets: stores, HTTP client, signals."""
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from core.collection import CollectionStore
from core.completion import CompletionIndex
from core.environment import EnvironmentStore
from core.history import HistoryStore
from core.http_client import HttpClient
from core.request_preparer import context_for
from core.settings import Settings
from core.variables import VarContext


class AppContext(QObject):
    environments_changed = Signal()
    collections_changed = Signal()
    history_changed = Signal()
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.envs = EnvironmentStore()
        self.collections = CollectionStore()
        self.history = HistoryStore(limit=int(self.settings["max_history_size"]))
        self.completion = CompletionIndex()
        self.completion.bind(self.history, self.collections)
        self.http = HttpClient(self)
        self.http.apply_settings(self.settings)
        self.history_changed.connect(self.completion.invalidate)
        self.collections_changed.connect(self.completion.invalidate)
        self.settings_changed.connect(self._on_settings)

    def _on_settings(self):
        self.http.apply_settings(self.settings)
        self.history.set_limit(int(self.settings["max_history_size"]))

    def locate(self, item_id: Optional[str]) -> Tuple[Optional[dict], tuple]:
        """(collection, ancestors) of a saved request, or (None, ())."""
        if not item_id:
            return None, ()
        found = self.collections.find(item_id)
        if not found:
            return None, ()
        col, _item, ancestors = found
        return col, ancestors

    def var_context(self, collection: Optional[dict] = None, local: Dict[str, str] = None) -> VarContext:
        return context_for(self.envs, collection, local)

    def apply_script_env(self, changes: Dict[str, str], removed=()):
        """Persists variables set by scripts (env['x'] = ...)."""
        if not changes and not removed:
            return
        for key, value in changes.items():
            self.envs.set_var(key, value)
        for key in removed:
            self.envs.unset_var(key)
        self.envs.save()
        self.environments_changed.emit()
