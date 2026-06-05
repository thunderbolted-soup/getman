import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple

import yaml
from prance import ResolvingParser
from prance.util import url

from core.logger import get_logger

logger = get_logger()


def detect_openapi_version(spec: dict) -> str:
    if "swagger" in spec:
        v = str(spec["swagger"])
        if v.startswith("2"):
            return "2.0"
    if "openapi" in spec:
        v = str(spec["openapi"])
        if v.startswith("3.1"):
            return "3.1"
        if v.startswith("3"):
            return "3.0"
    return "unknown"


def load_openapi_spec(source_path: str) -> Optional[Dict[str, Any]]:
    try:
        parser = ResolvingParser(source_path, strict=False)
        return parser.specification
    except Exception as e:
        logger.error(f"Failed to parse OpenAPI spec: {e}")
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                raw = f.read()
            spec = yaml.safe_load(raw) if source_path.endswith((".yaml", ".yml")) else json.loads(raw)
            if not spec:
                return None
            return spec
        except Exception as e2:
            logger.error(f"Fallback parse also failed: {e2}")
            return None


def _get_base_url(spec: dict, version: str) -> Tuple[str, Dict[str, str]]:
    env_vars = {}
    base_url = ""

    if version == "2.0":
        scheme = (spec.get("schemes") or ["http"])[0]
        host = spec.get("host", "localhost")
        base_path = spec.get("basePath", "")
        base_url = f"{scheme}://{host}{base_path}"
    else:
        servers = spec.get("servers", [{"url": ""}])
        server = servers[0] if servers else {"url": ""}
        raw_url = server.get("url", "")
        variables = server.get("variables", {})

        for var_name, var_info in variables.items():
            default_val = var_info.get("default", "")
            env_vars[var_name] = default_val

        def replace_var(match):
            var_name = match.group(1)
            val = env_vars.get(var_name, match.group(0))
            return "{{" + var_name + "}}"

        base_url = re.sub(r"\{(\w+)\}", replace_var, raw_url)

    return base_url, env_vars


def _get_auth_name(scheme_name: str, scheme: dict) -> str:
    s_type = scheme.get("type", "unknown")
    if s_type == "http":
        return scheme.get("scheme", "bearer")
    if s_type == "apiKey":
        return f"apiKey-{scheme.get('name', 'key')}"
    if s_type == "oauth2":
        return "oauth2"
    return scheme_name


def _convert_auth_scheme(scheme_name: str, scheme: dict) -> Optional[dict]:
    s_type = scheme.get("type", "")
    if s_type == "http":
        s_scheme = scheme.get("scheme", "bearer")
        if s_scheme == "bearer":
            return {"type": "bearer", "name": f"Bearer {scheme_name}", "data": {"token": ""}}
        if s_scheme == "basic":
            return {"type": "basic", "name": f"Basic {scheme_name}", "data": {"username": "", "password": ""}}
    if s_type == "apiKey":
        return {
            "type": "apikey",
            "name": f"API Key {scheme_name}",
            "data": {"key": scheme.get("name", "X-API-Key"), "value": "", "in": scheme.get("in", "header")},
        }
    if s_type == "oauth2":
        flows = scheme.get("flows", {})
        flow_type = list(flows.keys())[0] if flows else "implicit"
        auth_url = flows.get(flow_type, {}).get("authorizationUrl", "")
        token_url = flows.get(flow_type, {}).get("tokenUrl", "")
        return {
            "type": "oauth2",
            "name": f"OAuth2 {scheme_name}",
            "data": {"flow": flow_type, "authUrl": auth_url, "tokenUrl": token_url, "token": ""},
        }
    return None


def _extract_auth(spec: dict, version: str) -> List[dict]:
    auth_profiles = []
    if version == "2.0":
        sec_defs = spec.get("securityDefinitions", {})
        for name, scheme in sec_defs.items():
            profile = _convert_auth_scheme(name, scheme)
            if profile:
                auth_profiles.append(profile)
    else:
        sec_schemes = spec.get("components", {}).get("securitySchemes", {})
        for name, scheme in sec_schemes.items():
            profile = _convert_auth_scheme(name, scheme)
            if profile:
                auth_profiles.append(profile)
    return auth_profiles


def _build_security_requirements(security: List[dict], auth_profiles: List[dict]) -> dict:
    auth_headers = {}
    if not security:
        return auth_headers

    for req in security:
        for scheme_name, scopes in req.items():
            for profile in auth_profiles:
                if scheme_name in profile.get("name", ""):
                    ptype = profile.get("type")
                    pdata = profile.get("data", {})
                    if ptype == "bearer":
                        auth_headers["Authorization"] = "Bearer {{token}}"
                    elif ptype == "basic":
                        auth_headers["Authorization"] = "Basic {{basic_token}}"
                    elif ptype == "apikey":
                        if pdata.get("in") == "header":
                            auth_headers[pdata.get("key", "X-API-Key")] = "{{api_key}}"
    return auth_headers


def _generate_example_from_schema(schema: dict) -> Any:
    if not schema:
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "properties" in schema:
        result = {}
        for prop_name, prop_schema in schema["properties"].items():
            result[prop_name] = _generate_example_from_schema(prop_schema)
        return result
    s_type = schema.get("type", "")
    if s_type == "string":
        enum = schema.get("enum")
        return enum[0] if enum else "string"
    if s_type == "integer":
        return 0
    if s_type == "number":
        return 0.0
    if s_type == "boolean":
        return True
    if s_type == "array":
        items = schema.get("items", {})
        return [_generate_example_from_schema(items)] if items else []
    if schema.get("const"):
        return schema["const"]
    return None


def _build_request(
    method: str,
    path: str,
    operation: dict,
    base_url: str,
    auth_headers: dict,
) -> dict:
    method = method.upper()
    url = base_url.rstrip("/") + path

    headers = dict(auth_headers)
    params = {}
    path_params = {}

    operation_params = operation.get("parameters", [])

    for param in operation_params:
        p_name = param.get("name", "")
        p_in = param.get("in", "")
        p_required = param.get("required", False)

        if p_in == "header":
            default_val = _generate_example_from_schema(param.get("schema", {}))
            default_val = default_val if default_val is not None else ""
            headers[p_name] = str(default_val)

        elif p_in == "query":
            default_val = _generate_example_from_schema(param.get("schema", {}))
            default_val = default_val if default_val is not None else ""
            params[p_name] = str(default_val)

        elif p_in == "path":
            default_val = _generate_example_from_schema(param.get("schema", {}))
            default_val = default_val if default_val is not None else p_name
            path_params[p_name] = str(default_val)

    for p_name, p_val in path_params.items():
        url = url.replace(f"{{{p_name}}}", p_val)

    body = None
    body_mode = "none"
    request_body = operation.get("requestBody", operation.get("parameters", None))
    if isinstance(request_body, dict) and "content" in request_body:
        content = request_body.get("content", {})
        if "application/json" in content:
            media = content["application/json"]
            schema = media.get("schema", {})
            example = _generate_example_from_schema(schema)
            if example is not None:
                body = json.dumps(example, indent=2, ensure_ascii=False)
                body_mode = "raw"
                headers.setdefault("Content-Type", "application/json")
        elif "multipart/form-data" in content:
            media = content["multipart/form-data"]
            schema = media.get("schema", {})
            form_data = []
            for prop_name, prop_schema in schema.get("properties", {}).items():
                ex = _generate_example_from_schema(prop_schema)
                form_data.append({"key": prop_name, "value": str(ex) if ex is not None else "", "type": "Text"})
            body = form_data
            body_mode = "formdata"
        elif "application/x-www-form-urlencoded" in content:
            media = content["application/x-www-form-urlencoded"]
            schema = media.get("schema", {})
            urlencoded_data = {}
            for prop_name, prop_schema in schema.get("properties", {}).items():
                ex = _generate_example_from_schema(prop_schema)
                urlencoded_data[prop_name] = str(ex) if ex is not None else ""
            body = urlencoded_data
            body_mode = "urlencoded"
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    postman_request = {
        "method": method,
        "url": {
            "raw": url,
            "query": [{"key": k, "value": v} for k, v in params.items()] if params else [],
        },
        "header": [{"key": k, "value": v} for k, v in headers.items()] if headers else [],
    }

    if body is not None:
        if body_mode == "raw":
            postman_request["body"] = {"mode": "raw", "raw": body}
        elif body_mode == "formdata":
            postman_request["body"] = {"mode": "formdata", "formdata": body}
        elif body_mode == "urlencoded":
            postman_request["body"] = {"mode": "urlencoded", "urlencoded": body}

    return postman_request


def _get_operation_summary(operation: dict) -> str:
    summary = operation.get("summary", "")
    operation_id = operation.get("operationId", "")
    return summary or operation_id or ""


def _get_tags(operation: dict, path: str, spec: dict, version: str) -> List[str]:
    tags = operation.get("tags", [])
    if tags:
        return tags

    if version == "2.0":
        path_item = spec.get("paths", {}).get(path, {})
        tags = path_item.get("tags", [])

    return tags or ["General"]


def convert_to_collection(spec: dict) -> Tuple[dict, dict, List[dict]]:
    version = detect_openapi_version(spec)
    logger.info(f"Detected OpenAPI version: {version}")

    base_url, env_vars = _get_base_url(spec, version)
    auth_profiles = _extract_auth(spec, version)

    title = spec.get("info", {}).get("title", "Imported OpenAPI")
    description = spec.get("info", {}).get("description", "")

    collection = {
        "info": {
            "name": title,
            "description": description,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [],
    }

    paths = spec.get("paths", {})
    tag_groups: Dict[str, list] = {}

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not operation or not isinstance(operation, dict):
                continue

            tags = _get_tags(operation, path, spec, version)
            request = _build_request(method, path, operation, base_url, {})

            summary = _get_operation_summary(operation)
            request = _build_request(method, path, operation, base_url, {})

            item_name = summary or f"{method.upper()} {path}"
            item = {
                "name": item_name,
                "request": request,
                "_openapi_path": path,
            }

            for tag in tags:
                tag_groups.setdefault(tag, []).append(item)
                break
            logger.debug(f"Converted {method.upper()} {path} -> tag '{tags[0] if tags else '?'}'")

    for tag_name in sorted(tag_groups.keys()):
        items = tag_groups[tag_name]
        folder = {
            "name": tag_name,
            "item": items,
        }
        collection["item"].append(folder)

    if not collection["item"]:
        tag_groups.setdefault("Endpoints", [])

    return collection, env_vars, auth_profiles


def get_available_endpoints(spec: dict) -> List[dict]:
    endpoints = []
    paths = spec.get("paths", {})

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not operation or not isinstance(operation, dict):
                continue

            tags = _get_tags(operation, path, spec, detect_openapi_version(spec))
            summary = _get_operation_summary(operation)
            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": summary,
                "tags": tags,
            })

    return endpoints


def filter_collection_by_endpoints(collection: dict, selected_endpoints: List[dict]) -> dict:
    """Filters a converted collection to only include the selected endpoints.

    selected_endpoints should be a list of dicts with 'method' and 'path' keys.
    """
    selected_keys = {(ep["method"].upper(), ep["path"]) for ep in selected_endpoints}

    filtered_folders = []
    for folder in collection.get("item", []):
        filtered_items = []
        for item in folder.get("item", []):
            method = item.get("request", {}).get("method", "").upper()
            path = item.get("_openapi_path", "")
            if (method, path) in selected_keys:
                item.pop("_openapi_path", None)
                filtered_items.append(item)
        if filtered_items:
            new_folder = dict(folder)
            new_folder["item"] = filtered_items
            filtered_folders.append(new_folder)

    result = dict(collection)
    result["item"] = filtered_folders
    return result
