"""End-to-end UI tests against a local HTTP server (offscreen Qt)."""
import http.server
import json
import threading
import time

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import importers, paths  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path.startswith("/slow"):
            time.sleep(2)
        self.send_response(404 if "missing" in self.path else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "sid=abc; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(json.dumps({"method": self.command, "path": self.path,
                                     "auth": self.headers.get("Authorization"),
                                     "ctype": self.headers.get("Content-Type"),
                                     "body": body.decode(errors="replace"), "access_token": "tok-123"}).encode())

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    paths.set_data_dir(str(tmp_path))
    from ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    yield w
    w.close()
    w.deleteLater()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(predicate, timeout_ms=5000):
    waited = 0
    while not predicate() and waited < timeout_ms:
        wait(20)
        waited += 20
    assert predicate(), "condition not met in time"


def _collection(base):
    return {"info": {"name": "Demo", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}"}]},
            "variable": [{"key": "base", "value": base}],
            "item": [
                {"name": "Login", "request": {
                    "method": "POST", "url": "{{base}}/login", "auth": {"type": "noauth"},
                    "body": {"mode": "urlencoded", "urlencoded": [{"key": "user", "value": "{{user}}"}]}}},
                {"name": "Users", "item": [
                    {"name": "Get user", "request": {"method": "GET", "url": {
                        "raw": "{{base}}/users/:id", "variable": [{"key": "id", "value": "42"}]}}},
                    {"name": "Create", "request": {"method": "POST", "url": "{{base}}/users", "body": {
                        "mode": "raw", "raw": "{\"name\": \"{{user}}\"}", "options": {"raw": {"language": "json"}}}}},
                ]},
            ]}


def _setup(window, base):
    ctx = window.ctx
    col = ctx.collections.add(importers.parse_data(_collection(base)).collections[0])
    env = ctx.envs.add("Local", [{"key": "user", "value": "ann", "enabled": True}])
    ctx.envs.set_active(env["id"])
    ctx.collections_changed.emit()
    ctx.environments_changed.emit()
    return col


def _send(window):
    window.send_current()
    wait_for(lambda: window._current.job is None)
    return window._current


def test_post_script_token_flows_into_inherited_auth(window, server):
    col = _setup(window, server)
    login, create = col["items"][0], col["items"][1]["items"][1]
    window.open_saved(col["id"], login["id"])
    window.editor.show_section("scripts")
    window.editor.post_script.setPlainText("env['token'] = response.json()['access_token']\n"
                                           "test('ok', response.status == 200)")
    doc = _send(window)
    assert doc.response.status == 200
    assert json.loads(doc.response.body)["body"] == "user=ann"
    assert doc.tests == [("ok", True, "")]
    assert window.ctx.envs.active_vars()["token"] == "tok-123"

    window.open_saved(col["id"], create["id"], True)
    sent = json.loads(_send(window).response.body)
    assert sent["auth"] == "Bearer tok-123"
    assert sent["ctype"] == "application/json" and json.loads(sent["body"]) == {"name": "ann"}
    assert len(window.ctx.history.entries) == 2


def test_path_variables_and_params_sync(window, server):
    col = _setup(window, server)
    get_user = col["items"][1]["items"][0]
    window.open_saved(col["id"], get_user["id"])
    assert json.loads(_send(window).response.body)["path"] == "/users/42"

    window.new_tab()
    window.editor.url.setText(server + "/search?q=x&page=2")
    rows = window.editor.params.rows()
    assert [(r["key"], r["value"]) for r in rows] == [("q", "x"), ("page", "2")]
    rows[1]["enabled"] = False
    window.editor.params.set_rows(rows)
    window.editor._on_params_changed()
    assert window.editor.url.text() == server + "/search?q=x"
    assert json.loads(_send(window).response.body)["path"] == "/search?q=x"


def test_errors_and_cancel(window, server):
    window.editor.url.setText(server + "/missing")
    assert _send(window).response.status == 404
    window.editor.url.setText("http://127.0.0.1:1/nothing")
    doc = _send(window)
    assert doc.response is None and "Connection refused" in doc.error
    window.editor.url.setText(server + "/slow")
    window.send_current()
    assert window.editor.send_btn.text() == "Cancel"
    window.cancel_current()
    wait_for(lambda: window._current.job is None)
    assert window._current.error == "cancelled" and window.editor.send_btn.text() == "Send"
    window.editor.url.setText("")
    window.send_current()
    assert window._current.error == "Enter a request URL"


def test_save_dirty_state_and_session_restore(window, server):
    col = _setup(window, server)
    create = col["items"][1]["items"][1]
    window.open_saved(col["id"], create["id"])
    window.editor.url.setText(window.editor.url.text() + "?draft=1")
    window._sync_current()
    assert window._current.dirty
    assert "●" in window.tabbar.tabText(window.tabbar.currentIndex())
    assert window.save_current()
    assert not window._current.dirty
    assert window.ctx.collections.find(create["id"])[1]["url"].endswith("?draft=1")

    window.new_tab()
    window.editor.url.setText(server + "/unsaved")
    window.save_session()
    from ui.main_window import MainWindow
    restored = MainWindow()
    try:
        urls = [d.request["url"] for d in restored.docs]
        assert server + "/unsaved" in urls
        assert any(d.origin == create["id"] for d in restored.docs)
    finally:
        restored.close()
        restored.deleteLater()


def test_curl_paste_copy_and_autocomplete(window, server, app):
    window._on_curl_pasted(f"curl -X PUT '{server}/items' -H 'X-A: 1' --data-raw '{{\"a\": 1}}'")
    doc = window._current
    assert doc.request["method"] == "PUT" and doc.request["body"]["mode"] == "json"
    window.copy_curl()
    assert app.clipboard().text().startswith(f"curl -X PUT '{server}/items'")

    col = _setup(window, server)
    url = window.editor.url
    url.setText("{{ba")
    url.setCursorPosition(4)
    url.update_completions()
    assert url._model.rowCount() == 0  # unsaved tab: collection variables are not in scope
    window.open_saved(col["id"], col["items"][0]["id"], True)
    url.setText("{{ba")
    url.setCursorPosition(4)
    url.update_completions()
    assert [url._model.item(i).text() for i in range(url._model.rowCount())] == ["base"]
    url._on_activated("base")
    assert url.text() == "{{base}}"


def test_import_dialog_and_kv_bulk_edit(window, server):
    from ui.import_dialog import ImportDialog
    dlg = ImportDialog(window.ctx, window, text=json.dumps(_collection(server)))
    dlg._parse_pasted()
    assert dlg.ok.isEnabled()
    root = dlg.tree.topLevelItem(0)
    users = root.child(1)
    from PySide6.QtCore import Qt
    users.child(0).setCheckState(0, Qt.CheckState.Unchecked)  # skip "Get user"
    dlg._do_import()
    imported = dlg.imported_collections[0]
    from core.models import iter_requests
    assert [r["name"] for r, _ in iter_requests(imported)] == ["Login", "Create"]
    dlg.deleteLater()

    window.editor.show_section("headers")
    table = window.editor.headers
    table.set_rows([{"key": "A", "value": "1", "enabled": True}, {"key": "B", "value": "2", "enabled": False}])
    table.toggle_bulk()
    assert table.bulk_edit.toPlainText() == "A: 1\n//B: 2"
    table.bulk_edit.setPlainText("X: {{user}}\n//Y: 3")
    table.toggle_bulk()
    assert table.rows() == [{"key": "X", "value": "{{user}}", "enabled": True},
                            {"key": "Y", "value": "3", "enabled": False}]


def test_beautify_json_keeps_variables():
    from ui.request_editor import beautify_json
    assert beautify_json('{"a":{{num}},"b":"Bearer {{t}}","c":[1,2]}') == \
        '{\n  "a": {{num}},\n  "b": "Bearer {{t}}",\n  "c": [\n    1,\n    2\n  ]\n}'
