"""Raw URL helpers that never percent-decode, so ``{{vars}}`` and whatever the
user typed survive a round trip between the URL bar and the Params table."""
import re
from typing import List, Optional, Tuple

_PATH_VAR_RE = re.compile(r"(?<=/):([A-Za-z_][\w.-]*)")


def split_url(url: str) -> Tuple[str, Optional[str], str]:
    """Returns (base, query or None, fragment-with-#)."""
    fragment = ""
    hash_pos = url.find("#")
    if hash_pos >= 0:
        url, fragment = url[:hash_pos], url[hash_pos:]
    q = url.find("?")
    if q < 0:
        return url, None, fragment
    return url[:q], url[q + 1:], fragment


def parse_query(query: Optional[str]) -> List[Tuple[str, str]]:
    if not query:
        return []
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        pairs.append((key, value))
    return pairs


def build_query(pairs: List[Tuple[str, str]]) -> str:
    return "&".join(f"{k}={v}" if v != "" else k for k, v in pairs)


def replace_query(url: str, pairs: List[Tuple[str, str]]) -> str:
    base, _, fragment = split_url(url)
    if not pairs:
        return base + fragment
    return f"{base}?{build_query(pairs)}{fragment}"


def path_variables(url: str) -> List[str]:
    """Postman-style ``:name`` path segments (``/users/:id``)."""
    base, _, _ = split_url(url)
    scheme_end = base.find("://")
    path = base[scheme_end + 3:] if scheme_end >= 0 else base
    slash = path.find("/")
    if slash < 0:
        return []
    seen = []
    for m in _PATH_VAR_RE.finditer(path[slash:]):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def substitute_path_variables(url: str, values: dict) -> str:
    base, query, fragment = split_url(url)
    scheme_end = base.find("://")
    head_len = scheme_end + 3 if scheme_end >= 0 else 0
    slash = base.find("/", head_len)
    if slash < 0:
        return url
    path = _PATH_VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)) or m.group(0), base[slash:])
    rebuilt = base[:slash] + path
    if query is not None:
        rebuilt += "?" + query
    return rebuilt + fragment


def host_of(url: str) -> str:
    base, _, _ = split_url(url)
    rest = base.split("://", 1)[-1]
    return rest.split("/", 1)[0]
