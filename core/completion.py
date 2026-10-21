"""Autocomplete suggestions mined from history, collections and well-known
HTTP headers. The index is rebuilt lazily after history/collections change."""
from collections import OrderedDict
from typing import Dict, Iterable, List

COMMON_HEADERS = [
    "Accept", "Accept-Encoding", "Accept-Language", "Authorization", "Cache-Control",
    "Connection", "Content-Disposition", "Content-Encoding", "Content-Length", "Content-Type",
    "Cookie", "Host", "If-Match", "If-Modified-Since", "If-None-Match", "Origin", "Pragma",
    "Range", "Referer", "User-Agent", "X-API-Key", "X-Correlation-ID", "X-Forwarded-For",
    "X-Request-ID", "X-Requested-With",
]

COMMON_VALUES = {
    "accept": ["application/json", "*/*", "text/html", "application/xml", "text/plain"],
    "content-type": ["application/json", "application/x-www-form-urlencoded", "multipart/form-data",
                     "text/plain", "application/xml", "text/xml", "application/octet-stream"],
    "accept-encoding": ["gzip, deflate, br", "identity"],
    "cache-control": ["no-cache", "no-store", "max-age=0"],
    "connection": ["keep-alive", "close"],
    "authorization": ["Bearer {{token}}", "Basic "],
    "x-requested-with": ["XMLHttpRequest"],
}


def rank(query: str, candidates: Iterable[str], limit: int = 12) -> List[str]:
    """Prefix matches first, then matches at a word boundary, then substring
    matches. Candidate order (recency) breaks ties."""
    q = query.lower()
    buckets = ([], [], [])
    for cand in candidates:
        c = cand.lower()
        if not q:
            buckets[0].append(cand)
        elif c == q:
            continue
        elif c.startswith(q) or c.split("://", 1)[-1].startswith(q):
            buckets[0].append(cand)
        else:
            pos = c.find(q)
            if pos < 0:
                continue
            boundary = pos == 0 or not c[pos - 1].isalnum()
            buckets[1 if boundary else 2].append(cand)
        if len(buckets[0]) >= limit:
            break
    return (buckets[0] + buckets[1] + buckets[2])[:limit]


class CompletionIndex:
    def __init__(self):
        self.urls: List[str] = []
        self.header_keys: List[str] = list(COMMON_HEADERS)
        self.header_values: Dict[str, List[str]] = {k: list(v) for k, v in COMMON_VALUES.items()}
        self.param_keys: List[str] = []
        self.param_values: Dict[str, List[str]] = {}
        self._dirty = True
        self._sources = None

    def invalidate(self):
        self._dirty = True

    def bind(self, history_store, collection_store):
        self._sources = (history_store, collection_store)
        self._dirty = True

    def _ensure(self):
        if not self._dirty or not self._sources:
            return
        from core.models import iter_requests
        from core.urlutil import parse_query, split_url
        history, collections = self._sources
        urls: "OrderedDict[str, None]" = OrderedDict()
        hkeys: "OrderedDict[str, None]" = OrderedDict()
        hvals: Dict[str, "OrderedDict[str, None]"] = {}
        pkeys: "OrderedDict[str, None]" = OrderedDict()
        pvals: Dict[str, "OrderedDict[str, None]"] = {}

        def feed(req):
            url = req.get("url", "")
            if url:
                urls.setdefault(url)
                base = split_url(url)[0]
                if base != url:
                    urls.setdefault(base)
                for k, v in parse_query(split_url(url)[1]):
                    pkeys.setdefault(k)
                    if v:
                        pvals.setdefault(k, OrderedDict()).setdefault(v)
            for h in req.get("headers", []):
                if h.get("key"):
                    hkeys.setdefault(h["key"])
                    if h.get("value"):
                        hvals.setdefault(h["key"].lower(), OrderedDict()).setdefault(h["value"])
            for p in req.get("params", []):
                if p.get("key"):
                    pkeys.setdefault(p["key"])

        for entry in history.entries:
            feed(entry["request"])
        for col in collections.collections:
            for req, _ in iter_requests(col):
                feed(req)

        self.urls = list(urls)
        seen = {h.lower() for h in hkeys}
        self.header_keys = list(hkeys) + [h for h in COMMON_HEADERS if h.lower() not in seen]
        self.header_values = {k: list(v) for k, v in hvals.items()}
        for k, defaults in COMMON_VALUES.items():
            lst = self.header_values.setdefault(k, [])
            lst.extend(d for d in defaults if d not in lst)
        self.param_keys = list(pkeys)
        self.param_values = {k: list(v) for k, v in pvals.items()}
        self._dirty = False

    def suggest_urls(self, text: str) -> List[str]:
        self._ensure()
        return rank(text, self.urls)

    def suggest_header_keys(self, text: str) -> List[str]:
        self._ensure()
        return rank(text, self.header_keys)

    def suggest_header_values(self, key: str, text: str) -> List[str]:
        self._ensure()
        return rank(text, self.header_values.get(key.lower(), []))

    def suggest_param_keys(self, text: str) -> List[str]:
        self._ensure()
        return rank(text, self.param_keys)

    def suggest_param_values(self, key: str, text: str) -> List[str]:
        self._ensure()
        return rank(text, self.param_values.get(key, []))
