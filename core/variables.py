"""``{{variable}}`` resolution.

Lookup order (first wins): script-local values, active environment,
collection variables, globals. Values may reference other variables;
dynamic variables such as ``{{$guid}}`` are generated on every use.
"""
import datetime
import random
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

VAR_RE = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")
MAX_DEPTH = 8


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


DYNAMIC_VARS = {
    "$guid": lambda: str(uuid.uuid4()),
    "$randomUUID": lambda: str(uuid.uuid4()),
    "$timestamp": lambda: str(int(time.time())),
    "$timestampMs": lambda: str(int(time.time() * 1000)),
    "$isoTimestamp": _iso_now,
    "$randomInt": lambda: str(random.randint(0, 1000)),
    "$randomBoolean": lambda: random.choice(["true", "false"]),
    "$randomEmail": lambda: f"user{random.randint(1000, 99999)}@example.com",
    "$randomHex": lambda: f"{random.getrandbits(32):08x}",
}


class VarContext:
    """Layered variable lookup with the source of every value, so the UI can
    say where a variable came from."""

    LAYERS = ("local", "environment", "collection", "global")

    def __init__(self, environment: Mapping[str, str] = None, collection: Mapping[str, str] = None,
                 globals_: Mapping[str, str] = None, local: Mapping[str, str] = None):
        self.layers: Dict[str, Dict[str, str]] = {
            "local": dict(local or {}),
            "environment": dict(environment or {}),
            "collection": dict(collection or {}),
            "global": dict(globals_ or {}),
        }

    def lookup(self, name: str) -> Optional[Tuple[str, str]]:
        for layer in self.LAYERS:
            values = self.layers[layer]
            if name in values:
                return values[name], layer
        if name in DYNAMIC_VARS:
            return DYNAMIC_VARS[name](), "dynamic"
        return None

    def get(self, name: str) -> Optional[str]:
        found = self.lookup(name)
        return found[0] if found else None

    def names(self) -> List[Tuple[str, str, str]]:
        """All known variables as (name, value, source), shadowed ones removed."""
        seen = {}
        for layer in self.LAYERS:
            for k, v in self.layers[layer].items():
                seen.setdefault(k, (k, v, layer))
        result = list(seen.values())
        result.extend((k, "(generated on send)", "dynamic") for k in DYNAMIC_VARS)
        return result

    def as_flat_dict(self) -> Dict[str, str]:
        flat = {}
        for layer in reversed(self.LAYERS):
            flat.update(self.layers[layer])
        return flat


def resolve(text: Any, ctx, missing: set = None) -> Any:
    """Substitutes variables in ``text``; unknown ones are left as-is and
    reported through ``missing``. ``ctx`` is a VarContext or a plain mapping."""
    if not isinstance(text, str) or "{{" not in text:
        return text
    getter = ctx.get if hasattr(ctx, "get") else (lambda n: None)

    def repl(m):
        name = m.group(1)
        value = getter(name)
        if value is None:
            if missing is not None:
                missing.add(name)
            return m.group(0)
        return str(value)

    for _ in range(MAX_DEPTH):
        new = VAR_RE.sub(repl, text)
        if new == text or "{{" not in new:
            return new
        text = new
    return text


apply_env = resolve


def resolve_deep(data: Any, ctx, missing: set = None) -> Any:
    if isinstance(data, str):
        return resolve(data, ctx, missing)
    if isinstance(data, dict):
        return {resolve_deep(k, ctx, missing): resolve_deep(v, ctx, missing) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return type(data)(resolve_deep(v, ctx, missing) for v in data)
    return data


def find_vars(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, name) of every ``{{var}}`` in text."""
    if not text or "{{" not in text:
        return []
    return [(m.start(), m.end(), m.group(1)) for m in VAR_RE.finditer(text)]


def rows_to_dict(rows: Iterable[dict]) -> Dict[str, str]:
    return {r["key"]: r.get("value", "") for r in rows or [] if r.get("enabled", True) and r.get("key")}
