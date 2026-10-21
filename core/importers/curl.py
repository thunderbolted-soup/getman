"""cURL command parser (bash and Windows cmd line continuations)."""
import base64
import shlex

from core.models import kv, new_request
from core.urlutil import host_of, parse_query, split_url

_FLAGS_WITH_ARG = {
    "-o", "--output", "-b", "--cookie", "-c", "--cookie-jar", "-e", "--referer", "-m", "--max-time",
    "--connect-timeout", "-x", "--proxy", "-w", "--write-out", "--retry", "-r", "--range",
    "--cert", "--key", "--cacert", "-E", "--resolve", "--limit-rate", "-T", "--upload-file",
    "--proxy-user", "-U", "--max-redirs", "-K", "--config", "--interface", "--oauth2-bearer",
}

_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode", "--json"}


def parse_curl(text: str) -> dict:
    cleaned = text.replace("\\\r\n", " ").replace("\\\n", " ").replace("^\r\n", " ").replace("^\n", " ")
    cleaned = cleaned.replace("\r\n", " ").replace("\n", " ")
    try:
        parts = shlex.split(cleaned)
    except ValueError as e:
        from core.importers import ImportError_
        raise ImportError_(f"Cannot parse cURL command: {e}") from e
    if not parts or parts[0] != "curl":
        from core.importers import ImportError_
        raise ImportError_("Not a cURL command")

    method = None
    url = ""
    headers = []
    data_parts = []
    form = []
    user = None
    is_json = False
    force_get = False
    i = 1
    while i < len(parts):
        p = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        if p.startswith("--") and "=" in p and p.split("=", 1)[0] in _DATA_FLAGS | {"--url", "--request", "--header", "--user"}:
            p, nxt = p.split("=", 1)
            i -= 1  # value is glued; compensate for the "+= 2" below
        if p in ("-X", "--request") and nxt is not None:
            method = nxt.upper()
            i += 2
        elif p in ("-H", "--header") and nxt is not None:
            if ":" in nxt:
                k, v = nxt.split(":", 1)
                headers.append(kv(k.strip(), v.strip()))
            i += 2
        elif p in _DATA_FLAGS and nxt is not None:
            if p == "--json":
                is_json = True
            data_parts.append(nxt)
            i += 2
        elif p in ("-F", "--form", "--form-string") and nxt is not None:
            k, _, v = nxt.partition("=")
            if v.startswith("@") and p != "--form-string":
                form.append(kv(k, v[1:].split(";", 1)[0], type="file"))
            else:
                form.append(kv(k, v, type="text"))
            i += 2
        elif p in ("-u", "--user") and nxt is not None:
            user = nxt
            i += 2
        elif p in ("-A", "--user-agent") and nxt is not None:
            headers.append(kv("User-Agent", nxt))
            i += 2
        elif p == "--url" and nxt is not None:
            url = url or nxt
            i += 2
        elif p in ("-G", "--get"):
            force_get = True
            i += 1
        elif p in ("-I", "--head"):
            method = "HEAD"
            i += 1
        elif p in _FLAGS_WITH_ARG:
            i += 2
        elif p.startswith("-"):
            i += 1
        else:
            if not url:
                url = p
            i += 1

    if not url:
        from core.importers import ImportError_
        raise ImportError_("No URL found in cURL command")

    req = new_request(method=method or "GET", url=url)
    req["name"] = split_url(url)[0].split("://", 1)[-1][:80] or host_of(url) or "cURL request"
    req["headers"] = headers
    req["auth"]["type"] = "none"
    if user is not None:
        username, _, password = user.partition(":")
        req["auth"].update({"type": "basic", "username": username, "password": password})

    data = "&".join(data_parts)
    content_type = next((h["value"] for h in headers if h["key"].lower() == "content-type"), "").lower()
    if force_get and data:
        sep = "&" if "?" in url else "?"
        req["url"] = url + sep + data
    elif form:
        req["body"]["mode"] = "form"
        req["body"]["form"] = form
        method = method or "POST"
    elif data:
        method = method or "POST"
        if is_json or "json" in content_type or data.lstrip().startswith(("{", "[")):
            req["body"]["mode"] = "json"
            req["body"]["text"] = data
            if is_json and not content_type:
                headers.append(kv("Content-Type", "application/json"))
        elif "x-www-form-urlencoded" in content_type or (not content_type and "=" in data and " " not in data):
            from urllib.parse import unquote_plus
            req["body"]["mode"] = "urlencoded"
            req["body"]["urlencoded"] = [kv(unquote_plus(k), unquote_plus(v)) for k, v in parse_query(data)]
        elif "xml" in content_type:
            req["body"]["mode"] = "xml"
            req["body"]["text"] = data
        else:
            req["body"]["mode"] = "text"
            req["body"]["text"] = data
    req["method"] = method or "GET"
    req["params"] = [kv(k, v) for k, v in parse_query(split_url(req["url"])[1])]

    # Authorization: Basic xxx -> structured basic auth (nicer to edit)
    for h in list(headers):
        if h["key"].lower() == "authorization":
            value = h["value"]
            if value.lower().startswith("bearer "):
                req["auth"].update({"type": "bearer", "token": value[7:].strip()})
                headers.remove(h)
            elif value.lower().startswith("basic "):
                try:
                    decoded = base64.b64decode(value[6:].strip()).decode()
                    u, _, pw = decoded.partition(":")
                    req["auth"].update({"type": "basic", "username": u, "password": pw})
                    headers.remove(h)
                except ValueError:
                    pass
    return req
