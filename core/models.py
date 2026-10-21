"""Plain-dict data model shared by storage, importers and UI.

A collection is a tree::

    {"getman": 1, "id", "name", "description", "variables": [kv], "auth": auth,
     "items": [folder | request]}

    folder  = {"type": "folder", "id", "name", "auth", "items": [...]}
    request = {"type": "request", "id", "name", "method", "url", "params": [kv],
               "path_vars": [kv], "headers": [kv], "body": body, "auth": auth,
               "scripts": {"pre", "post"}, "description"}
    kv      = {"key", "value", "enabled"}            (form rows also have "type")
"""
import copy
import uuid
from typing import Any, Iterator, List, Optional, Tuple

FORMAT_VERSION = 1

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
BODY_MODES = ["none", "json", "text", "xml", "form", "urlencoded", "binary", "graphql"]
AUTH_TYPES = ["inherit", "none", "bearer", "basic", "apikey"]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def kv(key: str = "", value: Any = "", enabled: bool = True, **extra) -> dict:
    row = {"key": str(key), "value": "" if value is None else str(value), "enabled": bool(enabled)}
    row.update(extra)
    return row


def new_body() -> dict:
    return {"mode": "none", "text": "", "form": [], "urlencoded": [], "file": "",
            "graphql": {"query": "", "variables": ""}}


def new_auth(auth_type: str = "inherit") -> dict:
    return {"type": auth_type, "token": "", "username": "", "password": "",
            "key": "", "value": "", "in": "header"}


def new_request(name: str = "New Request", method: str = "GET", url: str = "") -> dict:
    return {
        "type": "request", "id": new_id(), "name": name, "method": method, "url": url,
        "params": [], "path_vars": [], "headers": [], "body": new_body(),
        "auth": new_auth(), "scripts": {"pre": "", "post": ""}, "description": "",
    }


def new_folder(name: str = "New Folder") -> dict:
    return {"type": "folder", "id": new_id(), "name": name, "auth": new_auth(), "items": []}


def new_collection(name: str = "New Collection") -> dict:
    return {"getman": FORMAT_VERSION, "id": new_id(), "name": name, "description": "",
            "variables": [], "auth": new_auth("none"), "items": []}


# --- normalisation (tolerant to hand-edited / older files) -------------------

def _norm_kv_list(rows, with_type: bool = False) -> List[dict]:
    out = []
    if isinstance(rows, dict):
        rows = [{"key": k, "value": v} for k, v in rows.items()]
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        row = kv(r.get("key", ""), r.get("value", ""), r.get("enabled", True))
        if with_type:
            row["type"] = "file" if str(r.get("type", "text")).lower() == "file" else "text"
        out.append(row)
    return out


def normalize_auth(auth, default_type: str = "inherit") -> dict:
    res = new_auth(default_type)
    if isinstance(auth, dict):
        for k in res:
            if k in auth and auth[k] is not None:
                res[k] = auth[k] if k == "type" else str(auth[k])
    if res["type"] not in AUTH_TYPES:
        res["type"] = default_type
    if res["in"] not in ("header", "query"):
        res["in"] = "header"
    return res


def normalize_request(req: dict) -> dict:
    res = new_request()
    if not isinstance(req, dict):
        return res
    res["id"] = str(req.get("id") or res["id"])
    res["name"] = str(req.get("name") or "Untitled")
    method = str(req.get("method") or "GET").upper().strip()
    res["method"] = method or "GET"
    res["url"] = str(req.get("url") or "")
    res["params"] = _norm_kv_list(req.get("params"))
    res["path_vars"] = _norm_kv_list(req.get("path_vars"))
    res["headers"] = _norm_kv_list(req.get("headers"))
    body = req.get("body") if isinstance(req.get("body"), dict) else {}
    b = res["body"]
    b["mode"] = body.get("mode") if body.get("mode") in BODY_MODES else "none"
    b["text"] = str(body.get("text") or "")
    b["form"] = _norm_kv_list(body.get("form"), with_type=True)
    b["urlencoded"] = _norm_kv_list(body.get("urlencoded"))
    b["file"] = str(body.get("file") or "")
    gql = body.get("graphql") if isinstance(body.get("graphql"), dict) else {}
    b["graphql"] = {"query": str(gql.get("query") or ""), "variables": str(gql.get("variables") or "")}
    res["auth"] = normalize_auth(req.get("auth"))
    scripts = req.get("scripts") if isinstance(req.get("scripts"), dict) else {}
    res["scripts"] = {"pre": str(scripts.get("pre") or ""), "post": str(scripts.get("post") or "")}
    res["description"] = str(req.get("description") or "")
    return res


def _normalize_items(items) -> List[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == "folder" or ("items" in it and it.get("type") != "request"):
            folder = new_folder(str(it.get("name") or "Folder"))
            folder["id"] = str(it.get("id") or folder["id"])
            folder["auth"] = normalize_auth(it.get("auth"))
            folder["items"] = _normalize_items(it.get("items"))
            out.append(folder)
        else:
            out.append(normalize_request(it))
    return out


def normalize_collection(col: dict) -> dict:
    res = new_collection(str(col.get("name") or "Collection"))
    res["id"] = str(col.get("id") or res["id"])
    res["description"] = str(col.get("description") or "")
    res["variables"] = _norm_kv_list(col.get("variables"))
    res["auth"] = normalize_auth(col.get("auth"), "none")
    if res["auth"]["type"] == "inherit":
        res["auth"]["type"] = "none"
    res["items"] = _normalize_items(col.get("items"))
    return res


# --- tree helpers --------------------------------------------------------------

def iter_requests(node: dict, parents: Tuple[dict, ...] = ()) -> Iterator[Tuple[dict, Tuple[dict, ...]]]:
    """Yields (request, ancestors) for every request below ``node``; ancestors
    run from the collection down to the direct parent."""
    chain = parents + (node,)
    for it in node.get("items", []):
        if it.get("type") == "folder":
            yield from iter_requests(it, chain)
        else:
            yield it, chain


def find_item(node: dict, item_id: str, parents: Tuple[dict, ...] = ()) -> Optional[Tuple[dict, Tuple[dict, ...]]]:
    chain = parents + (node,)
    for it in node.get("items", []):
        if it.get("id") == item_id:
            return it, chain
        if it.get("type") == "folder":
            found = find_item(it, item_id, chain)
            if found:
                return found
    return None


def count_requests(node: dict) -> int:
    return sum(1 for _ in iter_requests(node))


def clone_item(item: dict) -> dict:
    """Deep copy with fresh ids, so duplicates never collide with the original."""
    dup = copy.deepcopy(item)

    def _reid(it):
        it["id"] = new_id()
        for child in it.get("items", []):
            _reid(child)

    _reid(dup)
    return dup


def enabled_pairs(rows: List[dict]) -> List[Tuple[str, str]]:
    return [(r["key"], r.get("value", "")) for r in rows if r.get("enabled", True) and r.get("key")]
