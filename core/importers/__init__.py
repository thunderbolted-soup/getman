"""Import from many formats with auto-detection.

``parse_text(text, filename)`` returns an ImportResult with native
collections/environments; nothing is written to disk here.
"""
import json
from typing import List, Optional


class ImportError_(Exception):
    """Raised with a user-facing message when the input can't be imported."""


class ImportResult:
    def __init__(self, kind: str):
        self.kind = kind                      # human readable format name
        self.collections: List[dict] = []     # native collections
        self.environments: List[dict] = []    # {"name", "variables": [kv]}
        self.requests: List[dict] = []        # standalone requests (cURL)
        self.warnings: List[str] = []

    def summary(self) -> str:
        from core.models import count_requests
        parts = []
        n_req = sum(count_requests(c) for c in self.collections) + len(self.requests)
        if self.collections:
            parts.append(f"{len(self.collections)} collection" + ("s" if len(self.collections) != 1 else ""))
        parts.append(f"{n_req} request" + ("s" if n_req != 1 else ""))
        if self.environments:
            parts.append(f"{len(self.environments)} environment" + ("s" if len(self.environments) != 1 else ""))
        return " · ".join(parts)


def _load_structured(text: str, filename: str):
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(text)
        except ValueError as e:
            raise ImportError_(f"Invalid JSON: {e}") from e
    looks_yaml = filename.lower().endswith((".yaml", ".yml")) or any(
        stripped.startswith(p) for p in ("openapi:", "swagger:", "type: collection.insomnia", "_type:", "---"))
    if looks_yaml:
        try:
            import yaml  # optional dependency, loaded only for YAML input
        except ImportError as e:
            raise ImportError_("YAML import needs PyYAML: pip install pyyaml") from e
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ImportError_(f"Invalid YAML: {e}") from e
    return None


def detect(text: str, filename: str = "") -> str:
    stripped = text.lstrip()
    if stripped.startswith("curl ") or stripped.startswith("curl\t") or stripped == "curl":
        return "curl"
    data = _load_structured(text, filename)
    if data is None:
        from core.importers import httpfile
        if httpfile.looks_like(text) or filename.lower().endswith((".http", ".rest")):
            return "http"
        raise ImportError_("Unrecognized format. Supported: Postman, Insomnia, OpenAPI/Swagger, HAR, "
                           ".http files, cURL and Getman JSON.")
    return _detect_data(data)


def _detect_data(data) -> str:
    if isinstance(data, dict):
        if "getman" in data and "items" in data:
            return "getman"
        if "openapi" in data or "swagger" in data:
            return "openapi"
        if "info" in data and "item" in data:
            return "postman"
        if "values" in data and ("_postman_variable_scope" in data or "name" in data):
            return "postman_env"
        if data.get("_type") == "export" and "resources" in data:
            return "insomnia"
        if str(data.get("type", "")).startswith("collection.insomnia.rest/5") or \
                str(data.get("type", "")).startswith("environment.insomnia.rest/5"):
            return "insomnia5"
        if isinstance(data.get("log"), dict) and "entries" in data["log"]:
            return "har"
        if "collections" in data and "environments" in data:
            return "postman_dump"
        if "requests" in data and "order" in data:
            raise ImportError_("Postman Collection v1 is not supported — re-export it from Postman as v2.1.")
    raise ImportError_("Unrecognized JSON structure. Supported: Postman v2/v2.1, Insomnia, OpenAPI 2/3, "
                       "HAR and Getman JSON.")


def parse_text(text: str, filename: str = "") -> ImportResult:
    text = text.lstrip("﻿")
    if not text.strip():
        raise ImportError_("Nothing to import.")
    kind = detect(text, filename)
    if kind == "curl":
        from core.importers.curl import parse_curl
        res = ImportResult("cURL command")
        res.requests.append(parse_curl(text))
        return res
    if kind == "http":
        from core.importers import httpfile
        return httpfile.parse(text, filename)
    data = _load_structured(text, filename)
    return parse_data(data, kind, filename)


def parse_data(data, kind: Optional[str] = None, filename: str = "") -> ImportResult:
    kind = kind or _detect_data(data)
    if kind == "getman":
        from core.models import normalize_collection
        res = ImportResult("Getman collection")
        res.collections.append(normalize_collection(data))
        return res
    if kind == "postman":
        from core.importers import postman
        return postman.parse(data)
    if kind == "postman_env":
        from core.importers import postman
        return postman.parse_environment(data)
    if kind == "postman_dump":
        from core.importers import postman
        return postman.parse_dump(data)
    if kind in ("insomnia", "insomnia5"):
        from core.importers import insomnia
        return insomnia.parse(data) if kind == "insomnia" else insomnia.parse_v5(data)
    if kind == "openapi":
        from core.importers import openapi
        return openapi.parse(data)
    if kind == "har":
        from core.importers import har
        return har.parse(data, filename)
    raise ImportError_(f"Unsupported format: {kind}")


def parse_file(path: str) -> ImportResult:
    import os
    if os.path.getsize(path) > 50 * 1024 * 1024:
        raise ImportError_("File is too large to import (over 50 MB).")
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return parse_text(text, os.path.basename(path))
