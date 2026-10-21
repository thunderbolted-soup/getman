"""Insomnia export import: v4 (JSON "_type": "export") and v5 (YAML)."""
import json
import re
from typing import Dict, List

from core.models import kv, new_collection, new_folder, new_request, normalize_auth, normalize_collection
from core.urlutil import parse_query, split_url

# Insomnia uses Nunjucks: {{ _.baseUrl }} -> {{baseUrl}}; template tags {% ... %} are left as-is.
_VAR_RE = re.compile(r"\{\{\s*_\.([\w.-]+)\s*\}\}")


def _vars(text) -> str:
    return _VAR_RE.sub(r"{{\1}}", str(text or ""))


def _flatten(data, prefix="") -> List[dict]:
    rows = []
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                rows.extend(_flatten(v, key))
            else:
                rows.append(kv(key, _vars(v if not isinstance(v, (list, bool)) else json.dumps(v))))
    return rows


def _auth(auth) -> dict:
    if not isinstance(auth, dict) or not auth.get("type"):
        return normalize_auth(None)
    t = auth.get("type")
    if auth.get("disabled"):
        return normalize_auth({"type": "none"})
    if t == "bearer":
        return normalize_auth({"type": "bearer", "token": _vars(auth.get("token"))})
    if t == "basic":
        return normalize_auth({"type": "basic", "username": _vars(auth.get("username")),
                               "password": _vars(auth.get("password"))})
    if t == "apikey":
        return normalize_auth({"type": "apikey", "key": _vars(auth.get("key")), "value": _vars(auth.get("value")),
                               "in": "query" if auth.get("addTo") == "queryParams" else "header"})
    if t == "oauth2":
        return normalize_auth({"type": "bearer", "token": "{{accessToken}}"})
    if t == "none":
        return normalize_auth({"type": "none"})
    return normalize_auth(None)


def _request(r: dict) -> dict:
    url = _vars(r.get("url"))
    params = [kv(_vars(p.get("name")), _vars(p.get("value")), not p.get("disabled"))
              for p in r.get("parameters") or [] if isinstance(p, dict)]
    enabled = [(p["key"], p["value"]) for p in params if p["enabled"]]
    if enabled:
        url += ("&" if "?" in url else "?") + "&".join(f"{k}={v}" if v else k for k, v in enabled)
    req = new_request(str(r.get("name") or url or "Request"), str(r.get("method") or "GET").upper(), url)
    req["params"] = [kv(k, v) for k, v in parse_query(split_url(url)[1])] + [p for p in params if not p["enabled"]]
    req["headers"] = [kv(_vars(h.get("name")), _vars(h.get("value")), not h.get("disabled"))
                      for h in r.get("headers") or [] if isinstance(h, dict)]
    req["auth"] = _auth(r.get("authentication"))
    req["description"] = str(r.get("description") or "")
    body = r.get("body") or {}
    mime = str(body.get("mimeType") or "")
    b = req["body"]
    if mime == "application/graphql":
        try:
            gql = json.loads(body.get("text") or "{}")
        except ValueError:
            gql = {"query": body.get("text") or ""}
        variables = gql.get("variables")
        b["mode"] = "graphql"
        b["graphql"] = {"query": _vars(gql.get("query")),
                        "variables": json.dumps(variables, indent=2) if variables else ""}
    elif mime == "multipart/form-data":
        b["mode"] = "form"
        b["form"] = [kv(_vars(p.get("name")), _vars(p.get("fileName") if p.get("type") == "file" else p.get("value")),
                        not p.get("disabled"), type="file" if p.get("type") == "file" else "text")
                     for p in body.get("params") or []]
    elif mime == "application/x-www-form-urlencoded":
        b["mode"] = "urlencoded"
        b["urlencoded"] = [kv(_vars(p.get("name")), _vars(p.get("value")), not p.get("disabled"))
                           for p in body.get("params") or []]
    elif mime == "application/octet-stream" and body.get("fileName"):
        b["mode"] = "binary"
        b["file"] = str(body.get("fileName"))
    elif "text" in body:
        b["mode"] = "json" if "json" in mime else ("xml" if "xml" in mime else "text")
        b["text"] = _vars(body.get("text"))
    return req


def parse(data: dict):
    from core.importers import ImportResult
    res = ImportResult("Insomnia v4 export")
    resources = [x for x in data.get("resources") or [] if isinstance(x, dict)]
    by_parent: Dict[str, List[dict]] = {}
    for x in resources:
        by_parent.setdefault(x.get("parentId") or "", []).append(x)
    for lst in by_parent.values():
        lst.sort(key=lambda x: x.get("metaSortKey", 0))

    def build(parent_id: str) -> List[dict]:
        items = []
        for x in by_parent.get(parent_id, []):
            if x.get("_type") == "request_group":
                folder = new_folder(str(x.get("name") or "Folder"))
                folder["auth"] = _auth(x.get("authentication"))
                folder["items"] = build(x["_id"])
                items.append(folder)
            elif x.get("_type") == "request":
                items.append(_request(x))
            elif x.get("_type") in ("grpc_request", "websocket_request"):
                res.warnings.append(f"Skipped {x['_type'].replace('_', ' ')} \"{x.get('name', '')}\"")
        return items

    workspaces = [x for x in resources if x.get("_type") == "workspace"]
    if not workspaces:
        workspaces = [{"_id": "", "name": "Insomnia"}]
    for ws in workspaces:
        col = new_collection(str(ws.get("name") or "Insomnia"))
        col["description"] = str(ws.get("description") or "")
        col["items"] = build(ws["_id"])
        base_envs = [x for x in by_parent.get(ws["_id"], []) if x.get("_type") == "environment"]
        for base in base_envs:
            col["variables"].extend(_flatten(base.get("data")))
            for sub in by_parent.get(base["_id"], []):
                if sub.get("_type") == "environment":
                    res.environments.append({"name": str(sub.get("name") or "Environment"),
                                             "variables": _flatten(sub.get("data"))})
        if col["items"] or len(workspaces) == 1:
            res.collections.append(normalize_collection(col))
    return res


def parse_v5(data: dict):
    """Insomnia 9+/v5 YAML: nested "collection" items with "children"."""
    from core.importers import ImportResult
    res = ImportResult("Insomnia v5 export")

    def build(items) -> List[dict]:
        out = []
        for x in items or []:
            if not isinstance(x, dict):
                continue
            if "children" in x:
                folder = new_folder(str(x.get("name") or "Folder"))
                folder["auth"] = _auth(x.get("authentication"))
                folder["items"] = build(x.get("children"))
                out.append(folder)
            elif "url" in x:
                out.append(_request(x))
        return out

    meta_name = (data.get("name") or "Insomnia")
    col = new_collection(str(meta_name))
    col["items"] = build(data.get("collection"))
    envs = data.get("environments") or {}
    if isinstance(envs, dict):
        col["variables"] = _flatten(envs.get("data"))
        for sub in envs.get("subEnvironments") or []:
            if isinstance(sub, dict):
                res.environments.append({"name": str(sub.get("name") or "Environment"),
                                         "variables": _flatten(sub.get("data"))})
    if col["items"] or not res.environments:
        res.collections.append(normalize_collection(col))
    return res
