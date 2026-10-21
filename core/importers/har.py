"""HAR (HTTP Archive, e.g. "Save all as HAR" from browser DevTools) import.
Requests are grouped into folders by host; static assets are skipped."""
import os
from typing import Dict

from core.models import kv, new_collection, new_folder, new_request, normalize_collection
from core.urlutil import host_of, parse_query, split_url

_SKIP_HEADERS = {"content-length", "host", "connection", "accept-encoding", "cookie"}
_STATIC_TYPES = ("image/", "font/", "text/css", "javascript", "video/", "audio/")


def parse(data: dict, filename: str = ""):
    from core.importers import ImportResult
    res = ImportResult("HAR archive")
    name = os.path.splitext(filename)[0] if filename else "HAR import"
    col = new_collection(name or "HAR import")
    folders: Dict[str, dict] = {}
    skipped = 0
    seen = set()
    for entry in (data.get("log") or {}).get("entries") or []:
        src = entry.get("request") if isinstance(entry, dict) else None
        if not isinstance(src, dict) or not src.get("url"):
            continue
        mime = str(((entry.get("response") or {}).get("content") or {}).get("mimeType") or "")
        if src.get("method", "GET") == "GET" and any(t in mime for t in _STATIC_TYPES):
            skipped += 1
            continue
        url = src["url"]
        key = (src.get("method"), url, (src.get("postData") or {}).get("text"))
        if key in seen:
            continue
        seen.add(key)
        req = new_request(split_url(url)[0].split("://", 1)[-1][:100], str(src.get("method") or "GET").upper(), url)
        req["auth"]["type"] = "none"
        req["params"] = [kv(k, v) for k, v in parse_query(split_url(url)[1])]
        req["headers"] = [kv(h.get("name", ""), h.get("value", "")) for h in src.get("headers") or []
                          if isinstance(h, dict) and not str(h.get("name", "")).startswith(":")
                          and str(h.get("name", "")).lower() not in _SKIP_HEADERS]
        post = src.get("postData") or {}
        ptype = str(post.get("mimeType") or "")
        if post.get("params") and "multipart" in ptype:
            req["body"]["mode"] = "form"
            req["body"]["form"] = [kv(p.get("name", ""), p.get("fileName") or p.get("value", ""),
                                      type="file" if p.get("fileName") else "text") for p in post["params"]]
        elif post.get("params"):
            req["body"]["mode"] = "urlencoded"
            req["body"]["urlencoded"] = [kv(p.get("name", ""), p.get("value", "")) for p in post["params"]]
        elif post.get("text"):
            req["body"]["mode"] = "json" if "json" in ptype else ("xml" if "xml" in ptype else "text")
            req["body"]["text"] = post["text"]
        if "multipart" in ptype or "urlencoded" in ptype:
            req["headers"] = [h for h in req["headers"] if h["key"].lower() != "content-type"]
        host = host_of(url) or "requests"
        folder = folders.get(host)
        if folder is None:
            folder = folders[host] = new_folder(host)
        folder["items"].append(req)
    col["items"] = list(folders.values()) if len(folders) > 1 else (
        next(iter(folders.values()))["items"] if folders else [])
    res.collections.append(normalize_collection(col))
    if skipped:
        res.warnings.append(f"Skipped {skipped} static asset request(s) (images, scripts, styles, fonts).")
    return res
