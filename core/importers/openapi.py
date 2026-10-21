"""OpenAPI 3.0/3.1 and Swagger 2.0 import (JSON or YAML).

Local ``$ref`` pointers are resolved here directly — no heavy validator
dependencies. The base URL becomes the ``{{baseUrl}}`` collection variable,
``{id}`` path templates become ``:id`` path variables, operations are grouped
into folders by their first tag, and example bodies are generated from schemas.
"""
import json
import re
from typing import Any, Dict, List, Optional

from core.models import kv, new_collection, new_folder, new_request, normalize_auth, normalize_collection

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
MAX_DEPTH = 8


class _Resolver:
    def __init__(self, spec: dict):
        self.spec = spec

    def deref(self, node: Any, depth: int = 0) -> Any:
        while isinstance(node, dict) and "$ref" in node and depth < 32:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return {}  # external refs are not fetched
            target: Any = self.spec
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(target, dict) and part in target:
                    target = target[part]
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


def _param_example(param: dict, r: _Resolver) -> str:
    if "example" in param:
        return _scalar(param["example"])
    if isinstance(param.get("examples"), dict) and param["examples"]:
        first = r.deref(next(iter(param["examples"].values())))
        if isinstance(first, dict) and "value" in first:
            return _scalar(first["value"])
    schema = param.get("schema") or {k: v for k, v in param.items() if k in ("type", "enum", "default", "format", "items")}
    return _scalar(_example(schema, r))


def _base_url(spec: dict, version: str, variables: List[dict]) -> str:
    if version == "2.0":
        schemes = spec.get("schemes") or ["https"]
        host = spec.get("host") or "localhost"
        return f"{schemes[0]}://{host}{spec.get('basePath', '') or ''}".rstrip("/")
    servers = spec.get("servers") or [{"url": "/"}]
    server = servers[0] if isinstance(servers[0], dict) else {"url": "/"}
    url = str(server.get("url") or "/")
    for name, info in (server.get("variables") or {}).items():
        default = info.get("default", "") if isinstance(info, dict) else ""
        variables.append(kv(name, default))
    url = re.sub(r"\{([^{}]+)\}", r"{{\1}}", url)
    return url.rstrip("/")


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
                is_file = prop.get("format") in ("binary", "base64") or prop.get("type") == "file"
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


def parse(spec: dict):
    from core.importers import ImportResult
    version = "2.0" if str(spec.get("swagger", "")).startswith("2") else (
        "3.1" if str(spec.get("openapi", "")).startswith("3.1") else "3.0")
    r = _Resolver(spec)
    info = spec.get("info") or {}
    res = ImportResult(f"OpenAPI {version}" if version != "2.0" else "Swagger 2.0")
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
            req = new_request(str(name)[:120], method.upper(), "{{baseUrl}}" + url_path)
            req["description"] = str(op.get("description") or "")
            for p in plist:
                where, value = p.get("in"), None
                if where in ("query", "header", "path"):
                    value = _param_example(p, r)
                if where == "query":
                    req["params"].append(kv(p["name"], value, bool(p.get("required"))))
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
    return res
