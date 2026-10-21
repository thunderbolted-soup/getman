"""Single place that turns an editable request into what goes on the wire:
runs the pre-request script, resolves ``{{variables}}`` everywhere, applies
auth (with inheritance from folders/collection) and default headers, encodes
the body. Both sending and "Copy as cURL" go through ``prepare_request``.
"""
import base64
import copy
import json
import os
from typing import Dict, List, Optional, Sequence, Tuple

from core.models import enabled_pairs
from core.urlutil import split_url, substitute_path_variables
from core.variables import VarContext, resolve

USER_AGENT = "Getman/2.0"

AUTO_CONTENT_TYPES = {
    "json": "application/json",
    "xml": "application/xml",
    "text": "text/plain",
    "urlencoded": "application/x-www-form-urlencoded",
    "graphql": "application/json",
}


class PrepareError(Exception):
    pass


class PreparedRequest:
    def __init__(self):
        self.method = "GET"
        self.url = ""
        self.headers: List[Tuple[str, str]] = []
        self.body: Optional[bytes] = None
        self.multipart: Optional[List[dict]] = None  # [{"name", "value"} | {"name", "file"}]
        self.body_file: Optional[str] = None
        self.missing_vars: set = set()
        self.script = None  # core.scripting.ScriptResult
        self.warnings: List[str] = []

    def header(self, name: str) -> Optional[str]:
        name = name.lower()
        for k, v in self.headers:
            if k.lower() == name:
                return v
        return None


def effective_auth(request: dict, ancestors: Sequence[dict] = ()) -> dict:
    """Walks up folders to the collection while auth says "inherit"."""
    auth = request.get("auth") or {"type": "none"}
    for parent in reversed(tuple(ancestors)):
        if auth.get("type") != "inherit":
            break
        auth = parent.get("auth") or {"type": "inherit"}
    if auth.get("type") == "inherit":
        return {"type": "none"}
    return auth


def _has_header(headers: List[Tuple[str, str]], name: str) -> bool:
    name = name.lower()
    return any(k.lower() == name for k, _ in headers)


def _set_header(headers: List[Tuple[str, str]], name: str, value: str):
    lowered = name.lower()
    headers[:] = [(k, v) for k, v in headers if k.lower() != lowered]
    headers.append((name, value))


def prepare_request(request: dict, ctx: VarContext, ancestors: Sequence[dict] = (),
                    default_headers: Sequence[dict] = (), run_script: bool = True) -> PreparedRequest:
    prep = PreparedRequest()
    req = copy.deepcopy(request)
    missing = prep.missing_vars

    # 1. Pre-request script: may change the request and variables.
    code = req.get("scripts", {}).get("pre", "")
    if run_script and code.strip():
        from core.scripting import run_pre_script
        result = run_pre_script(code, req, ctx.as_flat_dict(), ctx.layers["local"])
        prep.script = result
        ctx.layers["local"].update(result.local_vars)
        ctx.layers["local"].update(result.env_changes)

    def r(text: str) -> str:
        return resolve(text, ctx, missing)

    # 2. URL with path variables.
    url = r(req.get("url", "")).strip()
    if not url:
        raise PrepareError("Enter a request URL")
    path_values = {k: r(v) for k, v in enabled_pairs(req.get("path_vars", []))}
    if path_values:
        url = substitute_path_variables(url, path_values)
    if "://" not in url.split("?", 1)[0]:
        url = "http://" + url
    prep.method = r(req.get("method", "GET")).upper() or "GET"

    # 3. Headers: defaults < request < auth.
    headers: List[Tuple[str, str]] = []
    for k, v in enabled_pairs(list(default_headers or [])):
        _set_header(headers, r(k), r(v))
    default_names = {k.lower() for k, _ in headers}
    for k, v in enabled_pairs(req.get("headers", [])):
        name, value = r(k), r(v)
        if name.lower() in default_names:
            _set_header(headers, name, value)
        else:
            headers.append((name, value))

    # 4. Auth.
    auth = effective_auth(req, ancestors)
    a_type = auth.get("type")
    if a_type == "bearer" and auth.get("token"):
        _set_header(headers, "Authorization", f"Bearer {r(auth['token'])}")
    elif a_type == "basic":
        raw = f"{r(auth.get('username', ''))}:{r(auth.get('password', ''))}".encode()
        _set_header(headers, "Authorization", "Basic " + base64.b64encode(raw).decode())
    elif a_type == "apikey" and auth.get("key"):
        key, value = r(auth["key"]), r(auth.get("value", ""))
        if auth.get("in") == "query":
            base, query, fragment = split_url(url)
            pair = f"{key}={value}"
            url = f"{base}?{query}&{pair}{fragment}" if query else f"{base}?{pair}{fragment}"
        else:
            _set_header(headers, key, value)
    prep.url = url

    # 5. Body.
    body = req.get("body", {})
    mode = body.get("mode", "none")
    if mode in ("json", "text", "xml"):
        prep.body = r(body.get("text", "")).encode("utf-8")
    elif mode == "graphql":
        gql = body.get("graphql", {})
        payload = {"query": r(gql.get("query", ""))}
        variables_text = r(gql.get("variables", "")).strip()
        if variables_text:
            try:
                payload["variables"] = json.loads(variables_text)
            except ValueError as e:
                prep.warnings.append(f"GraphQL variables are not valid JSON and were skipped: {e}")
        prep.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    elif mode == "urlencoded":
        from urllib.parse import urlencode
        prep.body = urlencode([(r(k), r(v)) for k, v in enabled_pairs(body.get("urlencoded", []))]).encode()
    elif mode == "form":
        parts = []
        for row in body.get("form", []):
            if not row.get("enabled", True) or not row.get("key"):
                continue
            if row.get("type") == "file":
                path = r(row.get("value", ""))
                if path and not os.path.isfile(path):
                    prep.warnings.append(f"File not found for form field '{row['key']}': {path}")
                parts.append({"name": r(row["key"]), "file": path})
            else:
                parts.append({"name": r(row["key"]), "value": r(row.get("value", ""))})
        prep.multipart = parts
        headers = [(k, v) for k, v in headers if k.lower() != "content-type"]
    elif mode == "binary":
        path = r(body.get("file", ""))
        if path and not os.path.isfile(path):
            prep.warnings.append(f"Body file not found: {path}")
        prep.body_file = path or None
        if not _has_header(headers, "Content-Type"):
            headers.append(("Content-Type", "application/octet-stream"))

    if mode in AUTO_CONTENT_TYPES and not _has_header(headers, "Content-Type"):
        headers.append(("Content-Type", AUTO_CONTENT_TYPES[mode]))
    if not _has_header(headers, "User-Agent"):
        headers.append(("User-Agent", USER_AGENT))
    if not _has_header(headers, "Accept"):
        headers.append(("Accept", "*/*"))
    prep.headers = headers
    if missing:
        prep.warnings.append("Unresolved variables: " + ", ".join(sorted(missing)))
    return prep


def _q(value: str) -> str:
    """POSIX shell single-quoting."""
    return "'" + str(value).replace("'", "'\\''") + "'"


def generate_curl(prep: PreparedRequest) -> str:
    has_body = prep.body is not None or prep.multipart is not None or prep.body_file
    parts = ["curl"]
    if prep.method == "HEAD":
        parts.append("--head")
    elif prep.method != "GET" or has_body:
        if not (prep.method == "POST" and has_body):
            parts.append(f"-X {prep.method}")
    parts.append(_q(prep.url))
    lines = [" ".join(parts)]
    for k, v in prep.headers:
        if k == "User-Agent" and v == USER_AGENT or (k == "Accept" and v == "*/*"):
            continue
        lines.append(f"-H {_q(f'{k}: {v}')}")
    if prep.multipart is not None:
        for part in prep.multipart:
            if "file" in part:
                lines.append(f"-F {_q(part['name'] + '=@' + part['file'])}")
            else:
                lines.append(f"-F {_q(part['name'] + '=' + part['value'])}")
    elif prep.body_file:
        lines.append(f"--data-binary {_q('@' + prep.body_file)}")
    elif prep.body is not None:
        lines.append(f"--data-raw {_q(prep.body.decode('utf-8', errors='replace'))}")
    return " \\\n  ".join(lines)


def context_for(env_store, collection: Optional[dict], local: Dict[str, str] = None) -> VarContext:
    from core.variables import rows_to_dict
    return VarContext(environment=env_store.active_vars(),
                      collection=rows_to_dict(collection.get("variables", [])) if collection else {},
                      globals_=env_store.global_vars(), local=local)
