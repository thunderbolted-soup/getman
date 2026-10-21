"""``.http`` / ``.rest`` files (JetBrains HTTP Client, VS Code REST Client).

    @host = https://api.example.com
    ### Get user
    GET {{host}}/users/1
    Accept: application/json

    ### Create
    POST {{host}}/users
    Content-Type: application/json

    {"name": "Ann"}
"""
import os
import re

from core.models import kv, new_collection, new_request, normalize_collection
from core.urlutil import parse_query, split_url

_REQUEST_LINE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE|CONNECT)\s+(\S.*?)(\s+HTTP/[\d.]+)?\s*$",
                           re.IGNORECASE)
_VAR_DEF = re.compile(r"^@([\w.-]+)\s*=\s*(.*)$")


def looks_like(text: str) -> bool:
    for line in text.splitlines()[:50]:
        s = line.strip()
        if not s or s.startswith(("#", "//")) or _VAR_DEF.match(s):
            continue
        return bool(_REQUEST_LINE.match(s)) or s.lower().startswith(("http://", "https://"))
    return False


def parse(text: str, filename: str = ""):
    from core.importers import ImportResult
    res = ImportResult(".http file")
    col = new_collection(os.path.splitext(filename)[0] if filename else "HTTP file")
    blocks = re.split(r"^###.*$", text, flags=re.MULTILINE)
    titles = [m.group(0)[3:].strip() for m in re.finditer(r"^###.*$", text, flags=re.MULTILINE)]
    for index, block in enumerate(blocks):
        title = titles[index - 1] if index > 0 and index - 1 < len(titles) else ""
        lines = block.splitlines()
        i = 0
        req = None
        while i < len(lines):
            s = lines[i].strip()
            i += 1
            if not s:
                continue
            m = _VAR_DEF.match(s)
            if m:
                col["variables"].append(kv(m.group(1), m.group(2).strip()))
                continue
            if s.startswith("#") or s.startswith("//"):
                name = re.match(r"^(?:#|//)\s*@name\s+(.+)$", s)
                if name:
                    title = name.group(1).strip()
                continue
            m = _REQUEST_LINE.match(s)
            if m:
                req = new_request(method=m.group(1).upper(), url=m.group(2).strip())
            elif s.lower().startswith(("http://", "https://", "{{")):
                req = new_request(method="GET", url=s)
            break
        if req is None:
            continue
        # URL continuation lines (?a=1 / &b=2) then headers until a blank line
        while i < len(lines) and lines[i].strip().startswith(("?", "&")):
            req["url"] += lines[i].strip()
            i += 1
        while i < len(lines) and lines[i].strip():
            line = lines[i].strip()
            i += 1
            if line.startswith(("#", "//")):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                req["headers"].append(kv(k.strip(), v.strip()))
        body_lines = [ln for ln in lines[i:] if not ln.strip().startswith(("> ", "<> "))]
        body = "\n".join(body_lines).strip()
        if body:
            ctype = next((h["value"].lower() for h in req["headers"] if h["key"].lower() == "content-type"), "")
            if "x-www-form-urlencoded" in ctype:
                req["body"]["mode"] = "urlencoded"
                req["body"]["urlencoded"] = [kv(k, v) for k, v in parse_query(body.replace("\n", ""))]
            else:
                req["body"]["mode"] = "json" if "json" in ctype or body.startswith(("{", "[")) else (
                    "xml" if "xml" in ctype else "text")
                req["body"]["text"] = body
        req["params"] = [kv(k, v) for k, v in parse_query(split_url(req["url"])[1])]
        req["name"] = title or f"{req['method']} {split_url(req['url'])[0].split('://', 1)[-1]}"[:100]
        req["auth"]["type"] = "inherit"
        col["items"].append(req)
    res.collections.append(normalize_collection(col))
    return res
