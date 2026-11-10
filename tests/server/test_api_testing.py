"""API testing dari dashboard: suite per aplikasi, impor, susun dengan AI, jalankan, Excel format laporan."""
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from qa_agent.llm.fake import FakeLLM
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        ok = self.headers.get("X-Api-Key") == "kunci"
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": {"status": "OPEN"}}).encode())

    def do_POST(self):  # noqa: N802
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b'{"data": {"id": 9}}')

    def log_message(self, *a):
        pass


AI_REPLY = json.dumps({"cases": [
    {"name": "Buat WO valid", "method": "POST", "path": "/wo", "body": "{\"teknisi\":\"T-01\"}",
     "assertions": [{"kind": "status", "op": "eq", "expected": "201"}], "capture": {"wo_id": "data.id"}},
    {"name": "Buat WO tanpa teknisi", "method": "POST", "path": "/wo", "body": "{}",
     "assertions": [{"kind": "status", "op": "eq", "expected": "422"}]}]})


@pytest.fixture
def ctx(tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore(),
                     llm_factory=lambda profile: FakeLLM([AI_REPLY]))
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="WFM API", platform="web", url=base)
        store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")
        yield client, app, a, base
    httpd.shutdown()


def suite_body(base, **over):
    data = {"name": "Work Order API", "base_url": base, "environment": "dev", "approved_hosts": [],
            "secret_headers": "X-Api-Key: kunci",
            "cases": [{"name": "Detail WO", "method": "GET", "url": "{{base_url}}/wo/1", "headers": {}, "body": "",
                       "assertions": [{"kind": "status", "op": "eq", "expected": "200", "path": ""},
                                      {"kind": "json", "op": "eq", "expected": "CLOSED", "path": "data.status"}],
                       "capture": {}}]}
    data.update(over)
    return data


def wait(client, run_id):
    for _ in range(100):
        run = client.get(f"/api/api-runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("tidak selesai")


def test_suite_run_and_excel_report(ctx):
    client, app, a, base = ctx
    r = client.post(f"/api/apps/{a.id}/api-suites", json=suite_body(base))
    assert r.status_code == 201, r.text
    suite = r.json()
    assert suite["has_secret_headers"] and "kunci" not in json.dumps(suite)
    run = client.post(f"/api/api-suites/{suite['id']}/run", json={}).json()
    done = wait(client, run["id"])
    case = done["result"]["cases"][0]
    assert done["status"] == "completed" and case["status"] == 200  # header rahasia terkirim
    assert case["passed"] is False and case["assertions"][1]["actual"] == "OPEN"  # temuan: status bukan CLOSED
    assert done["result"]["summary"] == {"total": 1, "passed": 0, "failed": 1, "errors": 0}
    x = client.get(f"/api/api-runs/{run['id']}/xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    ws = wb["Test Cases"]
    headers = [c.value for c in ws[1]]
    row = dict(zip(headers, [c.value for c in ws[2]]))
    assert row["Skenario"] == "Detail WO" and row["Status AI"] == "Fail"
    assert "JSON data.status = CLOSED" in row["Expected Result"] and "OPEN" in row["Actual Result"]
    assert "GET " in row["Langkah"]


def test_domain_safety_and_production_write_guard(ctx):
    client, app, a, base = ctx
    other = suite_body(base, base_url="https://api.orang-lain.example")
    r = client.post(f"/api/apps/{a.id}/api-suites", json=other)
    assert r.status_code == 422 and "api.orang-lain.example" in r.json()["detail"]
    prod = client.post(f"/api/apps/{a.id}/api-suites", json=suite_body(base, environment="production", cases=[
        {"name": "Buat", "method": "POST", "url": "{{base_url}}/wo", "headers": {}, "body": "{}", "assertions": [], "capture": {}}])).json()
    r = client.post(f"/api/api-suites/{prod['id']}/run", json={})
    assert r.status_code == 409 and "mengubah data" in r.json()["detail"]
    run = client.post(f"/api/api-suites/{prod['id']}/run", json={"confirm_production": True}).json()
    assert wait(client, run["id"])["status"] == "completed"


def test_import_and_ai_generate(ctx):
    client, app, a, base = ctx
    postman = {"info": {"name": "x"}, "item": [{"name": "Health", "request": {"method": "GET", "url": "{{base_url}}/health"}}]}
    r = client.post("/api/api-suites/import", json={"kind": "postman", "text": json.dumps(postman)})
    assert r.status_code == 200 and r.json()["cases"][0]["name"] == "Health"
    spec = {"openapi": "3.0.0", "servers": [{"url": base}], "paths": {"/wo": {"post": {
        "summary": "Buat WO", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "required": ["teknisi"],
                                                                                       "properties": {"teknisi": {"type": "string"}}}}}},
        "responses": {"201": {"description": "ok"}, "422": {"description": "validasi"}}}}}}
    r = client.post("/api/api-suites/import", json={"kind": "openapi", "text": json.dumps(spec)})
    assert r.json()["base_url"] == base and r.json()["cases"][0]["method"] == "POST"
    r = client.post("/api/api-suites/generate", json={"app_id": a.id, "spec_text": json.dumps(spec)})
    assert r.status_code == 200, r.text
    cases = r.json()["cases"]
    assert [c["name"] for c in cases] == ["Buat WO valid", "Buat WO tanpa teknisi"]
    assert cases[0]["url"] == "{{base_url}}/wo" and cases[0]["capture"] == {"wo_id": "data.id"}
    assert client.post("/api/api-suites/import", json={"kind": "openapi", "text": "bukan"}).status_code == 422
