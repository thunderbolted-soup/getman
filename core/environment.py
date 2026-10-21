"""Environments and global variables, stored in ``data/environments.json``."""
from typing import Dict, List, Optional

from core.models import kv, new_id
from core.paths import data_path
from core.storage import load_json, save_json
from core.variables import rows_to_dict


def _norm_vars(values) -> List[dict]:
    # Older Getman versions stored either {"k": "v"} or [{"key", "value"}].
    if isinstance(values, dict):
        return [kv(k, v) for k, v in values.items()]
    rows = []
    for r in values or []:
        if isinstance(r, dict) and "key" in r:
            rows.append(kv(r.get("key", ""), r.get("value", ""), r.get("enabled", True)))
    return rows


class EnvironmentStore:
    def __init__(self, path: str = None):
        self.path = path or data_path("environments.json")
        self.environments: List[dict] = []
        self.globals: List[dict] = []
        self.active_id: Optional[str] = None
        self.load()

    def load(self):
        raw = load_json(self.path, None)
        if isinstance(raw, list):  # legacy format: plain list of envs
            raw = {"environments": raw}
        raw = raw if isinstance(raw, dict) else {}
        self.environments = []
        for env in raw.get("environments", []):
            if not isinstance(env, dict):
                continue
            values = env.get("variables", env.get("values"))
            self.environments.append({"id": str(env.get("id") or new_id()),
                                      "name": str(env.get("name") or "Environment"),
                                      "variables": _norm_vars(values)})
        self.globals = _norm_vars(raw.get("globals"))
        self.active_id = raw.get("active")
        if not self.get(self.active_id):
            self.active_id = None

    def save(self):
        save_json(self.path, {"active": self.active_id, "globals": self.globals,
                              "environments": self.environments})

    def get(self, env_id: Optional[str]) -> Optional[dict]:
        for env in self.environments:
            if env["id"] == env_id:
                return env
        return None

    def active(self) -> Optional[dict]:
        return self.get(self.active_id)

    def set_active(self, env_id: Optional[str]):
        self.active_id = env_id if self.get(env_id) else None
        self.save()

    def add(self, name: str, variables: List[dict] = None) -> dict:
        env = {"id": new_id(), "name": self.unique_name(name), "variables": _norm_vars(variables)}
        self.environments.append(env)
        self.save()
        return env

    def unique_name(self, name: str) -> str:
        names = {e["name"] for e in self.environments}
        if name not in names:
            return name
        i = 2
        while f"{name} ({i})" in names:
            i += 1
        return f"{name} ({i})"

    def remove(self, env_id: str):
        self.environments = [e for e in self.environments if e["id"] != env_id]
        if self.active_id == env_id:
            self.active_id = None
        self.save()

    def active_vars(self) -> Dict[str, str]:
        env = self.active()
        return rows_to_dict(env["variables"]) if env else {}

    def global_vars(self) -> Dict[str, str]:
        return rows_to_dict(self.globals)

    def set_var(self, key: str, value: str, scope: str = "auto"):
        """Used by scripts: writes to the active environment, or to globals
        when no environment is selected (or scope == "global")."""
        env = self.active() if scope != "global" else None
        rows = env["variables"] if env else self.globals
        for r in rows:
            if r["key"] == key:
                r["value"] = str(value)
                r["enabled"] = True
                break
        else:
            rows.append(kv(key, value))

    def unset_var(self, key: str, scope: str = "auto"):
        env = self.active() if scope != "global" else None
        if env:
            env["variables"] = [r for r in env["variables"] if r["key"] != key]
        else:
            self.globals = [r for r in self.globals if r["key"] != key]
