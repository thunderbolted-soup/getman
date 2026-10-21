"""Python pre-request / post-response scripts.

Available names inside a script:
    env        dict of all variables; assignments are saved to the active
               environment (or to globals when no environment is selected)
    variables  dict of request-scoped variables (not saved)
    request    pre-request: .method .url .headers (dict) .body (str or None)
    response   post-response: .status .headers .text .json() .elapsed_ms
    test(name, condition)   records a check shown in the response Console
    log(...) / print(...)   writes to the Console
    json, re, time, datetime, hashlib, hmac, base64, uuid, random
"""
import json
import sys
from typing import Any, Dict, List, Optional


class EnvProxy(dict):
    """Dict that remembers which keys a script changed."""

    def __init__(self, initial: Dict[str, str]):
        super().__init__(initial)
        self.changes: Dict[str, str] = {}
        self.removed: set = set()

    def __setitem__(self, key, value):
        key, value = str(key), "" if value is None else str(value)
        super().__setitem__(key, value)
        self.changes[key] = value
        self.removed.discard(key)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.changes.pop(key, None)
        self.removed.add(key)

    def set(self, key, value):
        self[key] = value

    def unset(self, key):
        if key in self:
            del self[key]

    def pop(self, key, *default):
        if key in self:
            value = self[key]
            del self[key]
            return value
        if default:
            return default[0]
        raise KeyError(key)

    def update(self, other=(), **kwargs):
        for k, v in dict(other, **kwargs).items():
            self[k] = v

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


class ScriptRequest:
    def __init__(self, request: dict):
        self.method = request["method"]
        self.url = request["url"]
        self.headers: Dict[str, str] = {h["key"]: h.get("value", "") for h in request["headers"]
                                        if h.get("enabled", True) and h.get("key")}
        mode = request["body"]["mode"]
        self.body: Optional[str] = request["body"]["text"] if mode in ("json", "text", "xml") else None

    def apply_to(self, request: dict):
        request["method"] = str(self.method).upper()
        request["url"] = str(self.url)
        wanted = {str(k): "" if v is None else str(v) for k, v in self.headers.items()}
        lowered = {k.lower(): k for k in wanted}
        for h in request["headers"]:
            if not h.get("enabled", True) or not h.get("key"):
                continue
            match = lowered.pop(h["key"].lower(), None)
            if match is None:
                h["enabled"] = False
            else:
                h["value"] = wanted[match]
        for original in lowered.values():
            request["headers"].append({"key": original, "value": wanted[original], "enabled": True})
        if self.body is not None and request["body"]["mode"] in ("json", "text", "xml"):
            request["body"]["text"] = str(self.body)


class ScriptResponse:
    def __init__(self, response):
        self.status = response.status
        self.reason = response.reason
        self.headers = {k: v for k, v in response.headers}
        self.elapsed_ms = response.elapsed_ms
        self._body = response.body
        self._json = None

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    @property
    def content(self) -> bytes:
        return self._body

    def json(self) -> Any:
        if self._json is None:
            self._json = json.loads(self.text)
        return self._json

    def header(self, name: str, default: str = None) -> Optional[str]:
        name = name.lower()
        for k, v in self.headers.items():
            if k.lower() == name:
                return v
        return default


class ScriptResult:
    def __init__(self):
        self.logs: List[str] = []
        self.tests: List[tuple] = []  # (name, passed, message)
        self.error: Optional[str] = None
        self.env_changes: Dict[str, str] = {}
        self.env_removed: set = set()
        self.local_vars: Dict[str, str] = {}


def _run(code: str, names: Dict[str, Any], result: ScriptResult, label: str):
    def log(*args, **kwargs):
        result.logs.append(kwargs.get("sep", " ").join(str(a) for a in args))

    def test(name, condition=True):
        try:
            passed = bool(condition() if callable(condition) else condition)
            result.tests.append((str(name), passed, ""))
        except Exception as e:  # noqa: BLE001 - assertion failures are reported, not raised
            result.tests.append((str(name), False, f"{type(e).__name__}: {e}"))

    # Imported here, not at module level: most sessions never run a script.
    import base64
    import datetime
    import hashlib
    import hmac
    import random
    import re
    import time
    import uuid
    scope = {"__name__": "__getman_script__", "log": log, "print": log, "test": test,
             "json": json, "re": re, "time": time, "datetime": datetime, "hashlib": hashlib,
             "hmac": hmac, "base64": base64, "uuid": uuid, "random": random}
    scope.update(names)
    try:
        exec(compile(code, f"<{label}>", "exec"), scope)
    except Exception as e:  # noqa: BLE001 - script errors must never crash the app
        import traceback
        line = ""
        for frame in traceback.extract_tb(sys.exc_info()[2]):
            if frame.filename == f"<{label}>":
                line = f" (line {frame.lineno})"
        result.error = f"{label} script error{line}: {type(e).__name__}: {e}"


def run_pre_script(code: str, request: dict, variables: Dict[str, str],
                   local_vars: Dict[str, str]) -> ScriptResult:
    """Mutates ``request`` in place with whatever the script changed."""
    result = ScriptResult()
    env = EnvProxy(variables)
    local = dict(local_vars)
    script_request = ScriptRequest(request)
    _run(code, {"env": env, "variables": local, "request": script_request}, result, "pre-request")
    if result.error is None:
        script_request.apply_to(request)
    result.env_changes, result.env_removed = env.changes, env.removed
    result.local_vars = {str(k): str(v) for k, v in local.items()}
    return result


def run_post_script(code: str, response, variables: Dict[str, str],
                    local_vars: Dict[str, str]) -> ScriptResult:
    result = ScriptResult()
    env = EnvProxy(variables)
    local = dict(local_vars)
    _run(code, {"env": env, "variables": local, "response": ScriptResponse(response)},
         result, "post-response")
    result.env_changes, result.env_removed = env.changes, env.removed
    result.local_vars = {str(k): str(v) for k, v in local.items()}
    return result
