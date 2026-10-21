import json
import os
import tempfile

import pytest

os.environ.setdefault("GETMAN_DATA_DIR", tempfile.mkdtemp(prefix="getman-test-"))

from core import importers  # noqa: E402
from core.collection import CollectionStore  # noqa: E402
from core.completion import CompletionIndex, rank  # noqa: E402
from core.environment import EnvironmentStore  # noqa: E402
from core.history import HistoryStore  # noqa: E402
from core.models import count_requests, iter_requests, kv, new_collection, new_folder, new_request  # noqa: E402
from core.request_preparer import generate_curl, prepare_request  # noqa: E402
from core.scripting import run_post_script  # noqa: E402
from core.urlutil import path_variables, replace_query, split_url, substitute_path_variables  # noqa: E402
from core.variables import VarContext, find_vars, resolve  # noqa: E402


# --- variables -----------------------------------------------------------------

def test_resolve_layers_and_nesting():
    ctx = VarContext(environment={"host": "{{proto}}://api.local", "proto": "https"},
                     collection={"host": "ignored", "v": "2"}, globals_={"g": "G"})
    assert resolve("{{host}}/v{{ v }}/{{g}}", ctx) == "https://api.local/v2/G"
    missing = set()
    assert resolve("{{nope}}", ctx, missing) == "{{nope}}"
    assert missing == {"nope"}
    assert len(resolve("{{$guid}}", ctx)) == 36
    assert find_vars("a {{x}} b {{ y }}") == [(2, 7, "x"), (10, 17, "y")]


def test_resolve_self_reference_terminates():
    assert resolve("{{a}}", {"a": "{{a}}"}) == "{{a}}"


# --- url helpers -----------------------------------------------------------------

def test_url_query_roundtrip_keeps_raw_text():
    url = "https://x.io/a?q={{term}}&page=1#frag"
    base, query, frag = split_url(url)
    assert (base, query, frag) == ("https://x.io/a", "q={{term}}&page=1", "#frag")
    assert replace_query(url, [("q", "{{term}}"), ("flag", "")]) == "https://x.io/a?q={{term}}&flag#frag"
    assert replace_query(url, []) == "https://x.io/a#frag"


def test_path_variables():
    url = "{{baseUrl}}/users/:id/posts/:postId?x=:notpath"
    assert path_variables(url) == ["id", "postId"]
    assert substitute_path_variables("http://h:8080/users/:id?a=1", {"id": "7"}) == "http://h:8080/users/7?a=1"


# --- preparation -------------------------------------------------------------------

def test_prepare_request_full():
    col = new_collection("C")
    col["auth"] = {"type": "bearer", "token": "{{token}}"}
    folder = new_folder("F")
    req = new_request("R", "POST", "{{host}}/items/:id?x=1")
    req["path_vars"] = [kv("id", "{{itemId}}")]
    req["headers"] = [kv("X-One", "1"), kv("X-Off", "0", enabled=False)]
    req["body"]["mode"] = "json"
    req["body"]["text"] = '{"name": "{{name}}"}'
    req["scripts"]["pre"] = "env['name'] = 'Ann'\nrequest.headers['X-Sig'] = 'abc'"
    ctx = VarContext(environment={"host": "api.test", "token": "T", "itemId": "42"})
    prep = prepare_request(req, ctx, ancestors=(col, folder), default_headers=[kv("X-Default", "d")])
    assert prep.url == "http://api.test/items/42?x=1"
    headers = dict(prep.headers)
    assert headers["Authorization"] == "Bearer T"
    assert headers["X-Default"] == "d"
    assert headers["X-Sig"] == "abc"
    assert headers["Content-Type"] == "application/json"
    assert "X-Off" not in headers
    assert json.loads(prep.body) == {"name": "Ann"}
    assert prep.script.env_changes == {"name": "Ann"}
    curl = generate_curl(prep)
    assert curl.startswith("curl 'http://api.test/items/42?x=1'")
    assert "--data-raw '{\"name\": \"Ann\"}'" in curl


def test_prepare_auth_apikey_query_and_basic():
    req = new_request(url="https://h/x")
    req["auth"] = {"type": "apikey", "key": "k", "value": "v", "in": "query"}
    assert prepare_request(req, VarContext()).url == "https://h/x?k=v"
    req["auth"] = {"type": "basic", "username": "u", "password": "p"}
    assert prepare_request(req, VarContext()).header("authorization") == "Basic dTpw"


def test_prepare_urlencoded_and_form():
    req = new_request(method="POST", url="h/x")
    req["body"]["mode"] = "urlencoded"
    req["body"]["urlencoded"] = [kv("a b", "c&d"), kv("off", "1", enabled=False)]
    prep = prepare_request(req, VarContext())
    assert prep.body == b"a+b=c%26d"
    req["body"]["mode"] = "form"
    req["body"]["form"] = [kv("f", "v", type="text"), kv("file", "/nonexistent", type="file")]
    prep = prepare_request(req, VarContext())
    assert prep.multipart == [{"name": "f", "value": "v"}, {"name": "file", "file": "/nonexistent"}]
    assert any("File not found" in w for w in prep.warnings)
    assert "-F 'file=@/nonexistent'" in generate_curl(prep)


def test_script_error_is_reported():
    req = new_request(url="h")
    req["scripts"]["pre"] = "x = 1\nraise ValueError('boom')"
    prep = prepare_request(req, VarContext())
    assert "line 2" in prep.script.error and "boom" in prep.script.error


def test_post_script_tests_and_env():
    class Resp:
        status, reason, headers, elapsed_ms = 200, "OK", [("Content-Type", "application/json")], 5
        body = b'{"token": "abc"}'
    res = run_post_script("env['token'] = response.json()['token']\ntest('ok', response.status == 200)\n"
                          "test('bad', lambda: 1 / 0)", Resp(), {}, {})
    assert res.env_changes == {"token": "abc"}
    assert res.tests[0] == ("ok", True, "")
    assert res.tests[1][1] is False and "ZeroDivisionError" in res.tests[1][2]


# --- importers ---------------------------------------------------------------------

POSTMAN = {
    "info": {"name": "Demo", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "variable": [{"key": "base", "value": "https://api.x"}],
    "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{tok}}"}]},
    "item": [
        {"name": "Users", "item": [
            {"name": "Get user", "request": {
                "method": "GET",
                "url": {"raw": "{{base}}/users/:id?full=1", "query": [{"key": "full", "value": "1"},
                                                                        {"key": "debug", "value": "1", "disabled": True}],
                        "variable": [{"key": "id", "value": "5"}]},
                "header": [{"key": "Accept", "value": "application/json"}]},
             "event": [{"listen": "test", "script": {"exec": ["pm.test('x')"]}}]},
            {"name": "Create", "request": {
                "method": "POST", "url": "{{base}}/users",
                "auth": {"type": "noauth"},
                "body": {"mode": "raw", "raw": "{\"a\":1}", "options": {"raw": {"language": "json"}}}}},
        ]},
        {"name": "Upload", "request": {"method": "POST", "url": "{{base}}/up", "body": {
            "mode": "formdata", "formdata": [{"key": "f", "type": "file", "src": "/tmp/a.png"},
                                             {"key": "t", "value": "x", "type": "text"}]}}},
    ],
}


def test_postman_import_and_export_roundtrip():
    res = importers.parse_text(json.dumps(POSTMAN))
    assert res.kind == "Postman Collection v2.1"
    col = res.collections[0]
    assert count_requests(col) == 3
    assert col["auth"] == {**col["auth"], "type": "bearer", "token": "{{tok}}"}
    get_user = col["items"][0]["items"][0]
    assert get_user["path_vars"] == [kv("id", "5")]
    assert [p["key"] for p in get_user["params"]] == ["full", "debug"]
    assert get_user["params"][1]["enabled"] is False
    assert get_user["auth"]["type"] == "inherit"
    assert "pm.test" in get_user["scripts"]["post"] and res.warnings
    create = col["items"][0]["items"][1]
    assert create["auth"]["type"] == "none" and create["body"]["mode"] == "json"
    upload = col["items"][1]
    assert upload["body"]["form"][0] == {"key": "f", "value": "/tmp/a.png", "enabled": True, "type": "file"}

    from core.importers.postman import export_collection
    again = importers.parse_data(export_collection(col)).collections[0]
    strip = lambda c: [(r["name"], r["method"], r["url"], r["body"]["mode"], r["auth"]["type"])  # noqa: E731
                       for r, _ in iter_requests(c)]
    assert strip(again) == strip(col)


def test_postman_environment_import():
    res = importers.parse_text(json.dumps({"name": "Dev", "_postman_variable_scope": "environment",
                                           "values": [{"key": "a", "value": "1", "enabled": True}]}))
    assert res.environments == [{"name": "Dev", "variables": [kv("a", "1")]}]


def test_curl_import():
    text = """curl 'https://api.x/v1/items?limit=10' \\
      -X PUT -H 'Content-Type: application/json' -H "Authorization: Bearer abc" \\
      --data-raw '{"name":"it'"'"'s"}'"""
    res = importers.parse_text(text)
    req = res.requests[0]
    assert req["method"] == "PUT" and req["url"] == "https://api.x/v1/items?limit=10"
    assert req["auth"] == {**req["auth"], "type": "bearer", "token": "abc"}
    assert req["body"] == {**req["body"], "mode": "json", "text": '{"name":"it\'s"}'}
    assert req["params"] == [kv("limit", "10")]

    form = importers.parse_text("curl -F 'file=@/a/b.txt' -F 'x=1' -u me:pw http://h/up").requests[0]
    assert form["method"] == "POST" and form["body"]["mode"] == "form"
    assert form["body"]["form"][0]["type"] == "file" and form["auth"]["username"] == "me"

    urlenc = importers.parse_text("curl http://h/login -d 'user=a%20b&pw=1'").requests[0]
    assert urlenc["body"]["urlencoded"] == [kv("user", "a b"), kv("pw", "1")]


OPENAPI = {
    "openapi": "3.0.1",
    "info": {"title": "Pets"},
    "servers": [{"url": "https://{env}.pets.io/v1", "variables": {"env": {"default": "api"}}}],
    "security": [{"bearer": []}],
    "components": {
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "Pet": {"type": "object", "required": ["name"], "properties": {
                "id": {"type": "integer", "readOnly": True}, "name": {"type": "string", "example": "Rex"},
                "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
                "parent": {"$ref": "#/components/schemas/Pet"}}},
            "Tag": {"type": "object", "properties": {"label": {"type": "string"}}},
        },
    },
    "paths": {
        "/pets/{petId}": {
            "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "get": {"tags": ["pets"], "summary": "Get pet",
                    "parameters": [{"name": "verbose", "in": "query", "schema": {"type": "boolean"}}]},
            "put": {"tags": ["pets"], "operationId": "updatePet", "security": [],
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}}},
        },
        "/health": {"get": {}},
    },
}


def test_openapi_import():
    res = importers.parse_data(OPENAPI)
    col = res.collections[0]
    variables = {v["key"]: v["value"] for v in col["variables"]}
    assert variables["baseUrl"] == "https://{{env}}.pets.io/v1" and variables["env"] == "api"
    assert col["auth"]["type"] == "bearer" and col["auth"]["token"] == "{{bearerToken}}"
    folder = col["items"][0]
    assert folder["name"] == "pets"
    get_pet, update = folder["items"]
    assert get_pet["url"] == "{{baseUrl}}/pets/:petId"
    assert get_pet["path_vars"] == [kv("petId", "0")]
    assert get_pet["params"] == [kv("verbose", "true", False)]
    assert update["name"] == "updatePet" and update["auth"]["type"] == "none"
    body = json.loads(update["body"]["text"])
    assert body["name"] == "Rex" and "id" not in body and body["tags"] == [{"label": "string"}]
    assert col["items"][1]["name"] == "GET /health"


def test_openapi_yaml_and_swagger2():
    yaml_text = "swagger: '2.0'\ninfo: {title: Old}\nhost: old.io\nbasePath: /api\nschemes: [https]\n" \
                "paths:\n  /x:\n    post:\n      consumes: [application/x-www-form-urlencoded]\n" \
                "      parameters:\n        - {name: a, in: formData, type: string, required: true}\n"
    col = importers.parse_text(yaml_text, "spec.yaml").collections[0]
    assert col["variables"][0] == kv("baseUrl", "https://old.io/api")
    assert col["items"][0]["body"]["mode"] == "urlencoded"


def test_insomnia_v4_import():
    data = {"_type": "export", "__export_format": 4, "resources": [
        {"_id": "wrk", "_type": "workspace", "name": "Ins"},
        {"_id": "env", "_type": "environment", "parentId": "wrk", "data": {"base": "https://i.io", "nested": {"k": 1}}},
        {"_id": "env2", "_type": "environment", "parentId": "env", "name": "Prod", "data": {"base": "https://p.io"}},
        {"_id": "fld", "_type": "request_group", "parentId": "wrk", "name": "Group"},
        {"_id": "req", "_type": "request", "parentId": "fld", "name": "Login", "method": "POST",
         "url": "{{ _.base }}/login", "body": {"mimeType": "application/json", "text": "{}"},
         "headers": [{"name": "X", "value": "1"}], "parameters": [{"name": "q", "value": "2"}],
         "authentication": {"type": "bearer", "token": "{{ _.tok }}"}},
    ]}
    res = importers.parse_data(data)
    col = res.collections[0]
    req = col["items"][0]["items"][0]
    assert req["url"] == "{{base}}/login?q=2" and req["auth"]["token"] == "{{tok}}"
    assert {"key": "nested.k", "value": "1", "enabled": True} in col["variables"]
    assert res.environments[0]["name"] == "Prod"


def test_har_import():
    data = {"log": {"entries": [
        {"request": {"method": "GET", "url": "https://a.io/app.js", "headers": []},
         "response": {"content": {"mimeType": "application/javascript"}}},
        {"request": {"method": "POST", "url": "https://a.io/api?x=1",
                     "headers": [{"name": ":authority", "value": "a.io"}, {"name": "X-T", "value": "1"}],
                     "postData": {"mimeType": "application/json", "text": "{\"a\":1}"}},
         "response": {"content": {"mimeType": "application/json"}}},
    ]}}
    res = importers.parse_data(data, filename="session.har")
    reqs = [r for r, _ in iter_requests(res.collections[0])]
    assert len(reqs) == 1 and reqs[0]["headers"] == [kv("X-T", "1")] and reqs[0]["body"]["mode"] == "json"
    assert res.warnings


def test_http_file_import():
    text = "@host = https://h.io\n\n### List\nGET {{host}}/items\nAccept: application/json\n\n" \
           "### Create\nPOST {{host}}/items\nContent-Type: application/json\n\n{\"a\": 1}\n"
    res = importers.parse_text(text, "api.http")
    col = res.collections[0]
    assert col["variables"] == [kv("host", "https://h.io")]
    assert [r["name"] for r in col["items"]] == ["List", "Create"]
    assert col["items"][1]["body"]["text"] == '{"a": 1}'


def test_unknown_format():
    with pytest.raises(importers.ImportError_):
        importers.parse_text('{"hello": 1}')


# --- stores --------------------------------------------------------------------------

def test_stores_and_legacy_migration(tmp_path):
    coll_dir = tmp_path / "collections"
    coll_dir.mkdir()
    (coll_dir / "Old.json").write_text(json.dumps(POSTMAN))
    store = CollectionStore(str(coll_dir))
    assert store.collections[0]["name"] == "Demo"
    assert "getman" in json.loads((coll_dir / "Old.json").read_text())  # migrated in place
    created = store.create("New one")
    assert store.find(created["id"]) is None  # collections themselves aren't items
    assert CollectionStore(str(coll_dir)).get(created["id"])["name"] == "New one"

    env_file = tmp_path / "environments.json"
    env_file.write_text(json.dumps([{"name": "Legacy", "values": {"a": "1"}}]))
    envs = EnvironmentStore(str(env_file))
    assert envs.environments[0]["variables"] == [kv("a", "1")]
    envs.set_active(envs.environments[0]["id"])
    envs.set_var("b", "2")
    envs.save()
    assert EnvironmentStore(str(env_file)).active_vars() == {"a": "1", "b": "2"}

    hist = HistoryStore(str(tmp_path / "history.json"), limit=2)
    for i in range(3):
        hist.add(new_request(url=f"https://h/{i}"), 200, 10)
    assert [e["request"]["url"] for e in HistoryStore(str(tmp_path / "history.json")).entries] == \
        ["https://h/2", "https://h/1"]

    index = CompletionIndex()
    index.bind(hist, store)
    assert index.suggest_urls("h/1") == ["https://h/1"]
    assert "Content-Type" in index.suggest_header_keys("cont")
    assert index.suggest_header_values("content-type", "json")[0] == "application/json"


def test_rank_prefers_prefix():
    assert rank("us", ["/api/users", "users", "status"]) == ["users", "/api/users", "status"]


def test_openapi_external_file_refs(tmp_path):
    (tmp_path / "schemas").mkdir()
    (tmp_path / "common.yaml").write_text("Id: {type: integer, example: 7}\n")
    (tmp_path / "schemas" / "pet.yaml").write_text(
        "Pet:\n  type: object\n  properties:\n    id: {$ref: '../common.yaml#/Id'}\n"
        "    tag: {$ref: '#/Tag'}\nTag: {type: string, example: cute}\n")
    (tmp_path / "params.yaml").write_text("limit: {name: limit, in: query, required: true, schema: {type: integer}}\n")
    (tmp_path / "api.yaml").write_text(
        "openapi: 3.0.3\ninfo: {title: Split}\nservers: [{url: 'https://split.io'}]\npaths:\n  /pets:\n    post:\n"
        "      parameters: [{$ref: 'params.yaml#/limit'}]\n"
        "      requestBody: {content: {application/json: {schema: {$ref: 'schemas/pet.yaml#/Pet'}}}}\n")
    res = importers.parse_file(str(tmp_path / "api.yaml"))
    req = res.collections[0]["items"][0]
    assert json.loads(req["body"]["text"]) == {"id": 7, "tag": "cute"}
    assert req["url"] == "{{baseUrl}}/pets?limit=0" and not res.warnings
    pasted = importers.parse_text((tmp_path / "api.yaml").read_text(), "api.yaml")
    assert any("other files" in w for w in pasted.warnings)


def test_openapi_query_serialization_and_versions():
    def param(name, schema, **kw):
        return {"name": name, "in": "query", "required": True, "schema": schema, **kw}

    obj = {"type": "object", "properties": {"type": {"type": "string", "example": "account"},
                                            "user": {"type": "string", "example": "u1"}}}
    arr = {"type": "array", "items": {"type": "string", "example": "a"}, "example": ["a", "b"]}
    spec = {"openapi": "3.2.0", "info": {"title": "Q"}, "servers": [{"url": "https://q.io"}], "paths": {
        "/deep": {"get": {"parameters": [param("scope", obj, style="deepObject", explode=True)]}},
        "/form": {"get": {"parameters": [param("filter", obj), param("ids", arr)]}},
        "/csv": {"get": {"parameters": [param("ids", arr, explode=False), param("p", arr, style="pipeDelimited")]}},
        "/upload": {"post": {"servers": [{"url": "https://files.q.io/v2"}], "requestBody": {"content": {
            "multipart/form-data": {"schema": {"type": "object", "properties": {
                "file": {"type": "string", "contentMediaType": "image/png"}, "note": {"type": "string"}}}}}}}},
        "/raw": {"put": {"requestBody": {"content": {"application/octet-stream": {}}}}},
    }}
    res = importers.parse_data(spec)
    assert res.kind == "OpenAPI 3.2.0"
    deep, form, csv, upload, raw = res.collections[0]["items"]
    assert deep["url"] == "{{baseUrl}}/deep?scope[type]=account&scope[user]=u1"
    assert form["url"] == "{{baseUrl}}/form?type=account&user=u1&ids=a&ids=b"
    assert csv["url"] == "{{baseUrl}}/csv?ids=a,b&p=a|b"
    assert upload["url"] == "https://files.q.io/v2/upload"
    assert [(r["key"], r["type"]) for r in upload["body"]["form"]] == [("file", "file"), ("note", "text")]
    assert raw["body"]["mode"] == "binary"

    swagger = {"swagger": "2.0", "info": {"title": "S"}, "host": "s.io", "paths": {"/x": {"get": {"parameters": [
        {"name": "tags", "in": "query", "type": "array", "items": {"type": "string"}, "collectionFormat": "multi",
         "required": True, "x-example": None, "default": ["a", "b"]},
        {"name": "ids", "in": "query", "type": "array", "items": {"type": "integer"}, "required": True,
         "default": [1, 2]}]}}}}
    assert importers.parse_data(swagger).collections[0]["items"][0]["url"] == "{{baseUrl}}/x?tags=a&tags=b&ids=1,2"
