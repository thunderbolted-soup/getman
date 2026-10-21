"""OpenAPI 3.0/3.1 and Swagger 2.0 import (JSON or YAML).

``$ref`` pointers are resolved here directly — no heavy validator
dependencies: local ones (``#/components/...``) always, references to other
files (``schemas.yaml#/Pet``) when the spec was imported from a file. The base URL becomes the ``{{baseUrl}}`` collection variable,
``{id}`` path templates become ``:id`` path variables, operations are grouped
into folders by their first tag, and example bodies are generated from schemas.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from core.models import kv, new_collection, new_folder, new_request, normalize_auth, normalize_collection

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
MAX_DEPTH = 8


class _Resolver:
    MAX_FILE = 20 * 1024 * 1024

    def __init__(self, spec: dict, base_dir: Optional[str] = None):
        self.spec = spec
        self.base_dir = base_dir
        self.docs: Dict[str, Any] = {}
        self.unresolved: set = set()

    def _load(self, path: str) -> Any:
        """Loads a referenced file once; its refs are rewritten to absolute
        form so pointers inside it resolve against that file."""
        if path not in self.docs:
            self.docs[path] = None  # guards against reference cycles between files
            try:
                if os.path.getsize(path) > self.MAX_FILE:
                    raise ValueError("file too large")
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                if path.lower().endswith(".json"):
                    data = json.loads(text)
                else:
                    import yaml
                    data = yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
                self.docs[path] = self._absolutize(data, os.path.dirname(path), path)
            except Exception:  # noqa: BLE001 - unreadable or invalid file: reported as unresolved
                self.docs.pop(path, None)
                return None
        return self.docs[path]

    def _absolutize(self, node: Any, base: str, doc: str) -> Any:
        if isinstance(node, dict):
            out = {k: self._absolutize(v, base, doc) for k, v in node.items()}
            ref = node.get("$ref")
            if isinstance(ref, str) and "://" not in ref:
                file_part, _, frag = ref.partition("#")
                target = os.path.normpath(os.path.join(base, file_part)) if file_part else doc
                out["$ref"] = f"{target}#{frag}"
            return out
        if isinstance(node, list):
            return [self._absolutize(v, base, doc) for v in node]
        return node

    def deref(self, node: Any, depth: int = 0) -> Any:
        while isinstance(node, dict) and "$ref" in node and depth < 32:
            ref = node["$ref"]
            if not isinstance(ref, str):
                return {}
            file_part, _, pointer = ref.partition("#")
            if not file_part:
                target: Any = self.spec
            elif "://" in file_part or (not os.path.isabs(file_part) and not self.base_dir):
                self.unresolved.add(file_part)  # remote URLs are never fetched
                return {}
            else:
                path = file_part if os.path.isabs(file_part) else os.path.normpath(
                    os.path.join(self.base_dir, file_part))
                target = self._load(path)
                if target is None:
                    self.unresolved.add(file_part)
                    return {}
            for part in pointer.lstrip("/").split("/") if pointer.strip("/") else []:
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(target, dict) and part in target:
                    target = target[part]
                elif isinstance(target, list) and part.isdigit() and int(part) < len(target):
                    target = target[int(part)]
                else:
                    return {}
            node = target
            depth += 1
        return node


def _example(schema: Any, r: _Resolver, depth: int = 0) -> Any:
    schema = r.deref(schema)
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return None
    for key in ("example", "default", "const"):
        if key in schema:
            return schema[key]
    if isinstance(schema.get("examples"), list) and schema["examples"]:
        return schema["examples"][0]
    if schema.get("enum"):
        return schema["enum"][0]
    if "allOf" in schema:
        merged: Dict[str, Any] = {}
        for sub in schema["allOf"]:
            val = _example(sub, r, depth + 1)
            if isinstance(val, dict):
                merged.update(val)
        if merged:
            return merged
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return _example(schema[key][0], r, depth + 1)
    s_type = schema.get("type")
    if isinstance(s_type, list):
        s_type = next((t for t in s_type if t != "null"), None)
    if s_type == "object" or (s_type is None and "properties" in schema):
        props = schema.get("properties") or {}
        result = {}
        for name, prop in props.items():
            prop_r = r.deref(prop)
            if isinstance(prop_r, dict) and prop_r.get("readOnly"):
                continue
            result[name] = _example(prop_r, r, depth + 1)
        return result
    if s_type == "array":
        item = _example(schema.get("items"), r, depth + 1)
        return [item] if item is not None else []
    if s_type == "string":
        fmt = schema.get("format", "")
        return {"date-time": "2024-01-01T00:00:00Z", "date": "2024-01-01", "email": "user@example.com",
                "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "uri": "https://example.com",
                "binary": "", "byte": "", "password": "password"}.get(fmt, "string")
    if s_type == "integer":
        return 0
    if s_type == "number":
        return 0.0
    if s_type == "boolean":
        return True
    return None


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _param_value(param: dict, r: _Resolver) -> Any:
    if "example" in param:
        return param["example"]
    if isinstance(param.get("examples"), dict) and param["examples"]:
        first = r.deref(next(iter(param["examples"].values())))
        if isinstance(first, dict) and "value" in first:
            return first["value"]
    schema = param.get("schema")
    if schema is None and isinstance(param.get("content"), dict) and param["content"]:
        schema = (next(iter(param["content"].values())) or {}).get("schema")
    if schema is None:  # Swagger 2.0 keeps the schema keywords on the parameter itself
        schema = {k: v for k, v in param.items() if k in ("type", "enum", "default", "format", "items")}
    return _example(schema, r)


def _simple(value: Any) -> str:
    """OpenAPI "simple" style (path and header parameters): a,b,c / k1,v1,k2,v2."""
    if isinstance(value, list):
        return ",".join(_scalar(v) for v in value)
    if isinstance(value, dict):
        return ",".join(f"{k},{_scalar(v)}" for k, v in value.items())
    return _scalar(value)


def _param_example(param: dict, r: _Resolver) -> str:
    return _simple(_param_value(param, r))


def _deep_object(prefix: str, value: Any) -> List[tuple]:
    if isinstance(value, dict):
        pairs = []
        for k, v in value.items():
            pairs.extend(_deep_object(f"{prefix}[{k}]", v))
        return pairs
    if isinstance(value, list):
        return [pair for v in value for pair in _deep_object(f"{prefix}[]", v)]
    return [(prefix, _scalar(value))]


def _query_pairs(param: dict, value: Any, version: str) -> List[tuple]:
    """Serializes a query parameter the way the spec describes it (OpenAPI
    style/explode, Swagger 2.0 collectionFormat), so objects and arrays become
    real query strings instead of JSON."""
    name = param["name"]
    if version == "2.0":
        if isinstance(value, list):
            fmt = param.get("collectionFormat", "csv")
            items = [_scalar(v) for v in value]
            if fmt == "multi":
                return [(name, v) for v in items]
            return [(name, {"ssv": " ", "tsv": "\t", "pipes": "|"}.get(fmt, ",").join(items))]
        return [(name, _scalar(value))]
    style = param.get("style", "form")
    explode = param.get("explode", style == "form")
    if isinstance(value, dict):
        if style == "deepObject":
            return _deep_object(name, value)
        if explode:
            return [(k, _scalar(v)) for k, v in value.items()]
        return [(name, ",".join(f"{k},{_scalar(v)}" for k, v in value.items()))]
    if isinstance(value, list):
        if explode and style == "form":
            return [(name, _scalar(v)) for v in value] or [(name, "")]
        sep = {"spaceDelimited": " ", "pipeDelimited": "|"}.get(style, ",")
        return [(name, sep.join(_scalar(v) for v in value))]
    return [(name, _scalar(value))]


def _server_url(servers, variables: List[dict]) -> str:
    server = servers[0] if servers and isinstance(servers[0], dict) else {"url": "/"}
    url = str(server.get("url") or "/")
    for name, info in (server.get("variables") or {}).items():
        if not any(v["key"] == name for v in variables):
            default = info.get("default", "") if isinstance(info, dict) else ""
            variables.append(kv(name, default))
    return re.sub(r"\{([^{}]+)\}", r"{{\1}}", url).rstrip("/")


def _base_url(spec: dict, version: str, variables: List[dict]) -> str:
    if version == "2.0":
        schemes = spec.get("schemes") or ["https"]
        host = spec.get("host") or "localhost"
        return f"{schemes[0]}://{host}{spec.get('basePath', '') or ''}".rstrip("/")
    return _server_url(spec.get("servers"), variables)


def _auth_from_scheme(name: str, scheme: dict, variables: List[dict]) -> Optional[dict]:
    s_type = scheme.get("type")

    def var(key, default=""):
        if not any(v["key"] == key for v in variables):
            variables.append(kv(key, default))
        return "{{" + key + "}}"

    if s_type == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
        return {"type": "bearer", "token": var("bearerToken")}
    if (s_type == "http" and str(scheme.get("scheme", "")).lower() == "basic") or s_type == "basic":
        return {"type": "basic", "username": var("username"), "password": var("password")}
    if s_type == "apiKey":
        where = scheme.get("in", "header")
        if where == "cookie":
            return None
        return {"type": "apikey", "key": scheme.get("name", "X-API-Key"), "value": var("apiKey"),
                "in": "query" if where == "query" else "header"}
    if s_type in ("oauth2", "openIdConnect"):
        return {"type": "bearer", "token": var("accessToken")}
    return None


def _body(operation: dict, path_params: List[dict], version: str, spec: dict, r: _Resolver, req: dict):
    b = req["body"]
    if version == "2.0":
        consumes = operation.get("consumes") or spec.get("consumes") or ["application/json"]
        body_param = next((p for p in path_params if p.get("in") == "body"), None)
        form_params = [p for p in path_params if p.get("in") == "formData"]
        if body_param:
            example = _example(body_param.get("schema"), r)
            b["mode"] = "json"
            b["text"] = json.dumps(example, indent=2, ensure_ascii=False) if example is not None else "{}"
        elif form_params:
            multipart = any("multipart" in c for c in consumes) or any(p.get("type") == "file" for p in form_params)
            rows = [kv(p.get("name", ""), "" if p.get("type") == "file" else _param_example(p, r),
                       p.get("required", False), type="file" if p.get("type") == "file" else "text")
                    for p in form_params]
            if multipart:
                b["mode"], b["form"] = "form", rows
            else:
                b["mode"] = "urlencoded"
                b["urlencoded"] = [kv(x["key"], x["value"], x["enabled"]) for x in rows]
        return
    body = r.deref(operation.get("requestBody"))
    if not isinstance(body, dict):
        return
    content = body.get("content") or {}
    if not content:
        return
    json_type = next((c for c in content if c == "application/json" or c.endswith("+json")), None)
    if json_type:
        media = content[json_type] or {}
        example = media.get("example")
        if example is None and isinstance(media.get("examples"), dict) and media["examples"]:
            first = r.deref(next(iter(media["examples"].values())))
            example = first.get("value") if isinstance(first, dict) else None
        if example is None:
            example = _example(media.get("schema"), r)
        b["mode"] = "json"
        b["text"] = json.dumps(example, indent=2, ensure_ascii=False) if example is not None else "{}"
        return
    for ctype, mode in (("application/x-www-form-urlencoded", "urlencoded"), ("multipart/form-data", "form")):
        if ctype in content:
            schema = r.deref((content[ctype] or {}).get("schema")) or {}
            required = set(schema.get("required") or [])
            rows = []
            for name, prop in (schema.get("properties") or {}).items():
                prop = r.deref(prop) or {}
                is_file = (prop.get("format") in ("binary", "base64") or prop.get("type") == "file"
                           or "contentMediaType" in prop)  # OpenAPI 3.1 way to describe file parts
                value = "" if is_file else _scalar(_example(prop, r))
                rows.append(kv(name, value, name in required or not required,
                               **({"type": "file" if is_file else "text"} if mode == "form" else {})))
            b["mode"] = mode
            b[mode] = rows
            return
    xml_type = next((c for c in content if "xml" in c), None)
    if xml_type:
        b["mode"] = "xml"
        return
    if any(c.startswith("text/") for c in content):
        b["mode"] = "text"
        return
    if "application/octet-stream" in content or any(c.startswith(("image/", "audio/", "video/")) for c in content):
        b["mode"] = "binary"


def parse(spec: dict, base_dir: Optional[str] = None):
    from core.importers import ImportResult
    declared = str(spec.get("openapi") or spec.get("swagger") or "")
    version = "2.0" if str(spec.get("swagger", "")).startswith("2") else "3"
    r = _Resolver(spec, base_dir)
    info = spec.get("info") or {}
    res = ImportResult("Swagger 2.0" if version == "2.0" else f"OpenAPI {declared}")
    col = new_collection(str(info.get("title") or "OpenAPI"))
    col["description"] = str(info.get("description") or "")
    variables: List[dict] = []
    base = _base_url(spec, version, variables)
    variables.insert(0, kv("baseUrl", base))

    schemes = (spec.get("securityDefinitions") if version == "2.0"
               else (spec.get("components") or {}).get("securitySchemes")) or {}
    scheme_auth = {}
    for name, scheme in schemes.items():
        scheme = r.deref(scheme)
        if isinstance(scheme, dict):
            auth = _auth_from_scheme(name, scheme, variables)
            if auth:
                scheme_auth[name] = auth
    global_security = spec.get("security") or []
    default_scheme = None
    for requirement in global_security:
        default_scheme = next((n for n in (requirement or {}) if n in scheme_auth), None)
        if default_scheme:
            break
    col["auth"] = normalize_auth(scheme_auth[default_scheme] if default_scheme else {"type": "none"})

    folders: Dict[str, dict] = {}
    for path, path_item in (spec.get("paths") or {}).items():
        path_item = r.deref(path_item)
        if not isinstance(path_item, dict):
            continue
        common = [r.deref(p) for p in path_item.get("parameters") or []]
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            params: Dict[tuple, dict] = {}
            for p in common + [r.deref(p) for p in op.get("parameters") or []]:
                if isinstance(p, dict) and p.get("name"):
                    params[(p.get("name"), p.get("in"))] = p
            plist = list(params.values())
            url_path = re.sub(r"\{([^{}]+)\}", r":\1", path)
            name = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"
            # servers can be overridden per path or per operation (OpenAPI 3)
            servers = op.get("servers") or path_item.get("servers")
            prefix = _server_url(servers, variables) if servers and version != "2.0" else "{{baseUrl}}"
            req = new_request(str(name)[:120], method.upper(), prefix + url_path)
            req["description"] = str(op.get("description") or "")
            for p in plist:
                where, value = p.get("in"), None
                if where in ("header", "path"):
                    value = _param_example(p, r)
                if where == "query":
                    for key, val in _query_pairs(p, _param_value(p, r), version):
                        req["params"].append(kv(key, val, bool(p.get("required"))))
                elif where == "header":
                    if p["name"].lower() in ("authorization", "content-type", "accept"):
                        continue
                    req["headers"].append(kv(p["name"], value, bool(p.get("required"))))
                elif where == "path":
                    req["path_vars"].append(kv(p["name"], value))
            enabled_q = [(x["key"], x["value"]) for x in req["params"] if x["enabled"]]
            if enabled_q:
                req["url"] += "?" + "&".join(f"{k}={v}" for k, v in enabled_q)
            _body(op, plist, version, spec, r, req)

            if "security" in op:
                sec = op["security"] or []
                if not sec:
                    req["auth"] = normalize_auth({"type": "none"})
                else:
                    scheme_name = next((n for req_ in sec for n in (req_ or {}) if n in scheme_auth), None)
                    if scheme_name and scheme_name != default_scheme:
                        req["auth"] = normalize_auth(scheme_auth[scheme_name])
            tags = op.get("tags") or []
            if tags:
                folder = folders.get(tags[0])
                if folder is None:
                    folder = folders[tags[0]] = new_folder(str(tags[0]))
                folder["items"].append(req)
            else:
                col["items"].append(req)
    col["items"] = list(folders.values()) + col["items"]
    col["variables"] = variables
    res.collections.append(normalize_collection(col))
    if not base or base.startswith("/"):
        res.warnings.append("The spec has no absolute server URL — set the baseUrl collection variable.")
    if r.unresolved:
        where = "remote URLs are not downloaded" if base_dir else "import the spec from a file to resolve them"
        names = ", ".join(sorted(r.unresolved)[:3]) + (" …" if len(r.unresolved) > 3 else "")
        res.warnings.append(f"References to other files could not be resolved ({names}); {where}. "
                            "Affected bodies and parameters were left empty.")
    return res
