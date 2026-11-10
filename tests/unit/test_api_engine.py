"""Mesin API testing: assertion, variabel berantai, impor Postman/OpenAPI."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qa_agent.apitest.engine import ApiCase, Assertion, check, json_path, run_suite, substitute
from qa_agent.apitest.importers import from_openapi, from_postman, openapi_summary


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Trace", "abc")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/login":
            if body.get("password") == "benar":
                return self._send(200, {"data": {"token": "tok-123"}})
            return self._send(401, {"message": "Login gagal"})
        if self.path == "/wo":
            if self.headers.get("Authorization") != "Bearer tok-123":
                return self._send(401, {"message": "unauthorized"})
            if not body.get("teknisi"):
                return self._send(422, {"errors": {"teknisi": "wajib"}})
            return self._send(201, {"data": {"id": 77, "status": "OPEN", "items": [{"sku": "ONT"}]}})
        self._send(404, {})

    def do_GET(self):  # noqa: N802
        if self.path == "/wo/77":
            return self._send(200, {"data": {"id": 77, "status": "OPEN"}})
        self._send(404, {"message": "tidak ada"})

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_json_path_and_substitute():
    data = {"data": {"items": [{"sku": "ONT"}], "id": 7}}
    assert json_path(data, "data.items[0].sku") == (True, "ONT")
    assert json_path(data, "$.data.id") == (True, 7)
    assert json_path(data, "data.nope")[0] is False
    assert substitute("{{base}}/wo/{{id}}", {"base": "http://x", "id": 7}) == "http://x/wo/7"
    assert substitute("{{tidak_ada}}", {}) == "{{tidak_ada}}"


def test_check_assertions():
    resp = {"status": 201, "json": {"data": {"id": 77, "status": "OPEN"}}, "text": '{"data":...}', "ms": 120,
            "headers": {"x-trace": "abc"}}
    ok = [Assertion(kind="status", op="eq", expected="2xx"), Assertion(kind="json", path="data.status", op="eq", expected="OPEN"),
          Assertion(kind="json", path="data.id", op="type", expected="number"), Assertion(kind="time", op="lt", expected="500"),
          Assertion(kind="header", path="X-Trace", op="eq", expected="abc"), Assertion(kind="body", op="contains", expected="data")]
    assert all(check(a, resp)["passed"] for a in ok)
    bad = check(Assertion(kind="json", path="data.status", op="eq", expected="CLOSED"), resp)
    assert bad["passed"] is False and bad["actual"] == "OPEN"


def test_suite_chains_variables_and_reports(base):
    cases = [
        ApiCase(name="Login berhasil", method="POST", url="{{base}}/login", body='{"username":"qa","password":"{{password}}"}',
                assertions=[Assertion(kind="status", op="eq", expected="200")], capture={"token": "data.token"}),
        ApiCase(name="Buat WO", method="POST", url="{{base}}/wo", headers={"Authorization": "Bearer {{token}}"},
                body='{"teknisi":"T-01"}', assertions=[Assertion(kind="status", op="eq", expected="201"),
                                                        Assertion(kind="json", path="data.items[0].sku", op="eq", expected="ONT")],
                capture={"wo_id": "data.id"}),
        ApiCase(name="Detail WO", method="GET", url="{{base}}/wo/{{wo_id}}",
                assertions=[Assertion(kind="json", path="data.status", op="eq", expected="CLOSED")]),
        ApiCase(name="Validasi teknisi kosong", method="POST", url="{{base}}/wo", headers={"Authorization": "Bearer {{token}}"},
                body="{}", assertions=[Assertion(kind="status", op="eq", expected="422"),
                                       Assertion(kind="json", path="errors.teknisi", op="exists")]),
    ]
    result = run_suite(cases, variables={"base": base, "password": "benar"}, secrets=["benar"])
    by = {r["name"]: r for r in result["cases"]}
    assert by["Login berhasil"]["passed"] and result["variables"]["token"] == "••••••"  # token tidak bocor ke laporan
    assert result["variables"]["wo_id"] == 77
    assert by["Buat WO"]["passed"] and by["Buat WO"]["request"]["url"].endswith("/wo")
    assert by["Detail WO"]["passed"] is False  # status OPEN, expected CLOSED → temuan
    assert by["Detail WO"]["assertions"][0]["actual"] == "OPEN"
    assert by["Validasi teknisi kosong"]["passed"]
    assert result["summary"] == {"total": 4, "passed": 3, "failed": 1, "errors": 0}
    assert "benar" not in json.dumps(result)  # password disamarkan di hasil


def test_unreachable_is_error_not_crash():
    result = run_suite([ApiCase(name="mati", method="GET", url="http://127.0.0.1:9/x",
                                assertions=[Assertion(kind="status", op="eq", expected="200")])], timeout_s=0.5)
    case = result["cases"][0]
    assert case["passed"] is False and case["error"] and result["summary"]["errors"] == 1


def test_import_postman():
    collection = {"info": {"name": "WFM"}, "item": [
        {"name": "Auth", "item": [{"name": "Login", "request": {"method": "POST", "url": {"raw": "{{base}}/login"},
                                                                 "header": [{"key": "Content-Type", "value": "application/json"}],
                                                                 "body": {"mode": "raw", "raw": "{\"u\":1}"}}}]},
        {"name": "List WO", "request": {"method": "GET", "url": "{{base}}/wo"}}]}
    cases = from_postman(json.dumps(collection))
    assert [c.name for c in cases] == ["Auth / Login", "List WO"]
    assert cases[0].headers == {"Content-Type": "application/json"} and cases[0].body == '{"u":1}'
    assert cases[1].assertions[0].expected == "2xx"


def test_import_openapi():
    spec = {"openapi": "3.0.0", "servers": [{"url": "https://dev-api.test/v1"}], "paths": {
        "/wo": {"post": {"summary": "Buat WO", "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "required": ["teknisi"], "properties": {"teknisi": {"type": "string"}, "catatan": {"type": "string"}}}}}},
                         "responses": {"201": {"description": "dibuat"}, "422": {"description": "validasi"}}}},
        "/wo/{id}": {"get": {"operationId": "getWo", "responses": {"200": {"description": "ok"}}}}}}
    cases = from_openapi(json.dumps(spec))
    assert [(c.method, c.url) for c in cases] == [("POST", "{{base_url}}/wo"), ("GET", "{{base_url}}/wo/{{id}}")]
    assert cases[0].name == "Buat WO" and json.loads(cases[0].body) == {"teknisi": "string", "catatan": "string"}
    assert cases[0].assertions[0].expected == "201"
    summary = openapi_summary(json.dumps(spec))
    assert "POST /wo" in summary and "teknisi*" in summary and "422" in summary
    with pytest.raises(ValueError):
        from_openapi("bukan spec")
