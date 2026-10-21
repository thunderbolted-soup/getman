"""Postman Collection v2.0 / v2.1 and Postman environment import + v2.1 export."""
from typing import List

from core.models import (kv, new_collection, new_folder, new_request, normalize_auth,
                         normalize_collection)
from core.urlutil import parse_query, path_variables, split_url

SCHEMA_V21 = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
_LANG_TO_MODE = {"json": "json", "xml": "xml", "html": "text", "text": "text", "javascript": "text"}


def _rows(items, with_type=False) -> List[dict]:
    rows = []
    if isinstance(items, str):  # "Key: value\nKey2: value"
        for line in items.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                rows.append(kv(k.strip(), v.strip()))
        return rows
    for it in items or []:
        if not isinstance(it, dict):
            continue
        row = kv(it.get("key", ""), it.get("value", "") if it.get("value") is not None else "",
                 not it.get("disabled", False))
        if with_type:
            if it.get("type") == "file":
                src = it.get("src", "")
                if isinstance(src, list):
                    src = src[0] if src else ""
                row["type"], row["value"] = "file", str(src or "")
            else:
                row["type"] = "text"
        rows.append(row)
    return rows


def _auth(auth) -> dict:
    """Postman auth -> native. v2.1 stores params as [{key, value}], v2.0 as a dict."""
    if not isinstance(auth, dict):
        return normalize_auth(None)
    a_type = auth.get("type", "noauth")
    params = auth.get(a_type, {})
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    params = params or {}
    if a_type == "bearer":
        return normalize_auth({"type": "bearer", "token": params.get("token", "")})
    if a_type == "basic":
        return normalize_auth({"type": "basic", "username": params.get("username", ""),
                               "password": params.get("password", "")})
    if a_type == "apikey":
        return normalize_auth({"type": "apikey", "key": params.get("key", ""), "value": params.get("value", ""),
                               "in": "query" if params.get("in") == "query" else "header"})
    if a_type == "oauth2":
        return normalize_auth({"type": "bearer", "token": params.get("accessToken", "{{accessToken}}")})
    if a_type == "noauth":
        return normalize_auth({"type": "none"})
    return normalize_auth({"type": "none"})


def _url(url) -> tuple:
    """Returns (raw url, disabled query rows, path variables)."""
    if isinstance(url, str):
        return url, [], []
    if not isinstance(url, dict):
        return "", [], []
    raw = url.get("raw")
    if not raw:
        host = url.get("host", "")
        host = ".".join(host) if isinstance(host, list) else str(host or "")
        path = url.get("path", "")
        path = "/".join(str(p) for p in path) if isinstance(path, list) else str(path or "")
        raw = (f"{url['protocol']}://" if url.get("protocol") else "") + host
        if url.get("port"):
            raw += f":{url['port']}"
        if path:
            raw += "/" + path.lstrip("/")
        enabled = [(q.get("key", ""), q.get("value") or "") for q in url.get("query", []) or []
                   if isinstance(q, dict) and not q.get("disabled")]
        if enabled:
            raw += "?" + "&".join(f"{k}={v}" if v else k for k, v in enabled)
    disabled = [kv(q.get("key", ""), q.get("value") or "", False) for q in url.get("query", []) or []
                if isinstance(q, dict) and q.get("disabled")]
    path_vars = [kv(v.get("key", ""), v.get("value") or "") for v in url.get("variable", []) or []
                 if isinstance(v, dict)]
    return raw, disabled, path_vars


def _script(events, listen: str) -> str:
    for ev in events or []:
        if isinstance(ev, dict) and ev.get("listen") == listen:
            exec_ = (ev.get("script") or {}).get("exec", "")
            code = "\n".join(exec_) if isinstance(exec_, list) else str(exec_ or "")
            if code.strip():
                return code
    return ""


def _request(item: dict, stats: dict) -> dict:
    src = item.get("request")
    if isinstance(src, str):
        src = {"url": src, "method": "GET"}
    src = src or {}
    raw_url, disabled_q, path_vars = _url(src.get("url"))
    req = new_request(str(item.get("name") or raw_url or "Request"), str(src.get("method") or "GET").upper(), raw_url)
    req["params"] = [kv(k, v) for k, v in parse_query(split_url(raw_url)[1])] + disabled_q
    names = path_variables(raw_url)
    known = {p["key"]: p for p in path_vars}
    req["path_vars"] = [known.get(n, kv(n, "")) for n in names]
    req["headers"] = _rows(src.get("header"))
    req["auth"] = _auth(src["auth"]) if "auth" in src and src["auth"] else normalize_auth(None)
    desc = src.get("description") or item.get("description") or ""
    req["description"] = desc.get("content", "") if isinstance(desc, dict) else str(desc)

    body = src.get("body") or {}
    mode = body.get("mode")
    b = req["body"]
    if mode == "raw":
        lang = (((body.get("options") or {}).get("raw") or {}).get("language") or "").lower()
        text = body.get("raw") or ""
        if not lang:
            ctype = next((h["value"].lower() for h in req["headers"] if h["key"].lower() == "content-type"), "")
            lang = "json" if "json" in ctype or text.lstrip().startswith(("{", "[")) else (
                "xml" if "xml" in ctype else "text")
        b["mode"] = _LANG_TO_MODE.get(lang, "text")
        b["text"] = text
    elif mode == "urlencoded":
        b["mode"] = "urlencoded"
        b["urlencoded"] = _rows(body.get("urlencoded"))
    elif mode == "formdata":
        b["mode"] = "form"
        b["form"] = _rows(body.get("formdata"), with_type=True)
    elif mode == "file":
        b["mode"] = "binary"
        b["file"] = str((body.get("file") or {}).get("src") or "")
    elif mode == "graphql":
        gql = body.get("graphql") or {}
        b["mode"] = "graphql"
        b["graphql"] = {"query": str(gql.get("query") or ""), "variables": str(gql.get("variables") or "")}

    for listen in ("prerequest", "test"):
        js = _script(item.get("event"), listen)
        if js:
            stats["scripts"] += 1
            # JavaScript can't run here; keep it visible as a comment for manual porting.
            commented = "\n".join("# " + line for line in js.splitlines())
            key = "pre" if listen == "prerequest" else "post"
            req["scripts"][key] = f"# Postman {listen} script (JavaScript, not executed):\n{commented}\n"
    return req


def _items(items, stats) -> List[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if "item" in it:  # folder
            folder = new_folder(str(it.get("name") or "Folder"))
            folder["auth"] = _auth(it["auth"]) if it.get("auth") else normalize_auth(None)
            folder["items"] = _items(it.get("item"), stats)
            out.append(folder)
        elif "request" in it:
            out.append(_request(it, stats))
    return out


def parse_collection(data: dict, stats: dict = None) -> dict:
    stats = stats if stats is not None else {"scripts": 0}
    info = data.get("info") or {}
    col = new_collection(str(info.get("name") or "Postman Collection"))
    desc = info.get("description") or ""
    col["description"] = desc.get("content", "") if isinstance(desc, dict) else str(desc)
    col["variables"] = _rows(data.get("variable"))
    col["auth"] = _auth(data.get("auth")) if data.get("auth") else normalize_auth({"type": "none"})
    if col["auth"]["type"] == "inherit":
        col["auth"]["type"] = "none"
    col["items"] = _items(data.get("item"), stats)
    return normalize_collection(col)


def parse(data: dict):
    from core.importers import ImportResult
    schema = str((data.get("info") or {}).get("schema", ""))
    version = "v2.1" if "v2.1" in schema else ("v2.0" if "v2.0" in schema else "v2")
    res = ImportResult(f"Postman Collection {version}")
    stats = {"scripts": 0}
    res.collections.append(parse_collection(data, stats))
    if stats["scripts"]:
        res.warnings.append(f"{stats['scripts']} Postman JavaScript script(s) were kept as comments — "
                            "Getman scripts are written in Python.")
    return res


def parse_environment(data: dict):
    from core.importers import ImportResult
    res = ImportResult("Postman Environment")
    res.environments.append({"name": str(data.get("name") or "Environment"),
                             "variables": [kv(v.get("key", ""), v.get("value", ""), v.get("enabled", True))
                                           for v in data.get("values", []) if isinstance(v, dict)]})
    return res


def parse_dump(data: dict):
    """Postman "Export data" dump: many collections and environments."""
    from core.importers import ImportResult
    res = ImportResult("Postman data dump")
    stats = {"scripts": 0}
    for col in data.get("collections", []):
        if isinstance(col, dict) and "item" in col:
            res.collections.append(parse_collection(col, stats))
        elif isinstance(col, dict) and "requests" in col:
            res.warnings.append(f"Skipped v1 collection \"{col.get('name', '?')}\"")
    for env in data.get("environments", []):
        if isinstance(env, dict):
            res.environments.extend(parse_environment(env).environments)
    return res


# --- export -------------------------------------------------------------------

def _export_auth(auth: dict):
    t = auth.get("type")
    if t == "bearer":
        return {"type": "bearer", "bearer": [{"key": "token", "value": auth.get("token", ""), "type": "string"}]}
    if t == "basic":
        return {"type": "basic", "basic": [{"key": "username", "value": auth.get("username", ""), "type": "string"},
                                           {"key": "password", "value": auth.get("password", ""), "type": "string"}]}
    if t == "apikey":
        return {"type": "apikey", "apikey": [{"key": "key", "value": auth.get("key", ""), "type": "string"},
                                             {"key": "value", "value": auth.get("value", ""), "type": "string"},
                                             {"key": "in", "value": auth.get("in", "header"), "type": "string"}]}
    if t == "none":
        return {"type": "noauth"}
    return None


def _export_kv(rows, with_type=False):
    out = []
    for r in rows:
        item = {"key": r["key"], "value": r.get("value", "")}
        if not r.get("enabled", True):
            item["disabled"] = True
        if with_type:
            if r.get("type") == "file":
                item = {"key": r["key"], "type": "file", "src": r.get("value", "")}
            else:
                item["type"] = "text"
        out.append(item)
    return out


def _export_request(req: dict) -> dict:
    query = _export_kv(req["params"])
    url = {"raw": req["url"], "query": query} if query else {"raw": req["url"]}
    if req["path_vars"]:
        url["variable"] = [{"key": p["key"], "value": p["value"]} for p in req["path_vars"]]
    out = {"method": req["method"], "header": _export_kv(req["headers"]), "url": url}
    if req.get("description"):
        out["description"] = req["description"]
    auth = _export_auth(req["auth"])
    if auth:
        out["auth"] = auth
    b = req["body"]
    mode = b["mode"]
    if mode in ("json", "text", "xml"):
        lang = {"json": "json", "xml": "xml", "text": "text"}[mode]
        out["body"] = {"mode": "raw", "raw": b["text"], "options": {"raw": {"language": lang}}}
    elif mode == "urlencoded":
        out["body"] = {"mode": "urlencoded", "urlencoded": _export_kv(b["urlencoded"])}
    elif mode == "form":
        out["body"] = {"mode": "formdata", "formdata": _export_kv(b["form"], with_type=True)}
    elif mode == "binary":
        out["body"] = {"mode": "file", "file": {"src": b["file"]}}
    elif mode == "graphql":
        out["body"] = {"mode": "graphql", "graphql": dict(b["graphql"])}
    return out


def _export_items(items) -> list:
    out = []
    for it in items:
        if it.get("type") == "folder":
            folder = {"name": it["name"], "item": _export_items(it["items"])}
            auth = _export_auth(it.get("auth", {}))
            if auth:
                folder["auth"] = auth
            out.append(folder)
        else:
            out.append({"name": it["name"], "request": _export_request(it)})
    return out


def export_collection(col: dict) -> dict:
    data = {"info": {"_postman_id": col["id"], "name": col["name"], "description": col.get("description", ""),
                     "schema": SCHEMA_V21},
            "item": _export_items(col["items"])}
    if col.get("variables"):
        data["variable"] = [{"key": v["key"], "value": v["value"]} for v in col["variables"]]
    auth = _export_auth(col.get("auth", {}))
    if auth and auth.get("type") != "noauth":
        data["auth"] = auth
    return data


def export_environment(env: dict) -> dict:
    return {"name": env["name"], "_postman_variable_scope": "environment",
            "values": [{"key": v["key"], "value": v["value"], "enabled": v.get("enabled", True)}
                       for v in env["variables"]]}

