"""API uji beban: simpan skenario, pengaman domain/production, jalankan, pantau, hentikan, unduh Excel."""
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200 if self.headers.get("Authorization") == "Bearer rahasia" else 401)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


@pytest.fixture
def ctx(tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        a = app.state.store.create_app(name="WFM API", platform="web", url=base)
        yield client, app, a, base
    httpd.shutdown()


def body(base, **over):
    data = {"name": "Daftar WO 20 user", "secret_headers": "Authorization: Bearer rahasia",
            "requests": [{"name": "Daftar WO", "method": "GET", "url": f"{base}/wo", "headers": {}, "body": "", "weight": 1}],
            "profile": {"vus": 3, "duration_s": 1, "ramp_up_s": 0, "think_ms": 0},
            "thresholds": {"p95_ms": 2000, "error_rate_pct": 1}, "environment": "dev", "approved_hosts": []}
    data.update(over)
    return data


def wait_done(client, run_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/perf-runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.2)
    raise AssertionError("run tidak selesai")


def test_create_run_and_report(ctx):
    client, app, a, base = ctx
    r = client.post(f"/api/apps/{a.id}/perf-tests", json=body(base))
    assert r.status_code == 201, r.text
    test = r.json()
    assert test["has_secret_headers"] is True and "rahasia" not in json.dumps(test)
    run = client.post(f"/api/perf-tests/{test['id']}/run", json={}).json()
    assert run["status"] == "running"
    done = wait_done(client, run["id"])
    assert done["status"] == "completed" and done["result"]["summary"]["total"] > 0
    assert done["result"]["summary"]["errors"] == 0  # header rahasia terkirim
    assert done["result"]["verdict"]["passed"] is True and done["result"]["timeline"]
    runs = client.get(f"/api/perf-tests/{test['id']}/runs").json()
    assert [x["id"] for x in runs] == [run["id"]]
    x = client.get(f"/api/perf-runs/{run['id']}/xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Ringkasan", "Per Request", "Timeline"] and wb["Per Request"]["A2"].value == "Daftar WO"


def test_validation_and_safety(ctx):
    client, app, a, base = ctx
    # host di luar domain aplikasi wajib dikonfirmasi
    other = body(base, requests=[{"name": "x", "method": "GET", "url": "https://bukan-milik-kita.example/x"}])
    r = client.post(f"/api/apps/{a.id}/perf-tests", json=other)
    assert r.status_code == 422 and "bukan-milik-kita.example" in r.json()["detail"]
    other["approved_hosts"] = ["bukan-milik-kita.example"]
    assert client.post(f"/api/apps/{a.id}/perf-tests", json=other).status_code == 201
    # batas VU & durasi
    too_big = body(base, profile={"vus": 5000, "duration_s": 1})
    assert client.post(f"/api/apps/{a.id}/perf-tests", json=too_big).status_code == 422
    # production wajib konfirmasi saat dijalankan
    prod = client.post(f"/api/apps/{a.id}/perf-tests", json=body(base, environment="production")).json()
    r = client.post(f"/api/perf-tests/{prod['id']}/run", json={})
    assert r.status_code == 409 and "Production" in r.json()["detail"]
    run = client.post(f"/api/perf-tests/{prod['id']}/run", json={"confirm_production": True}).json()
    wait_done(client, run["id"])


def test_stop_running_test_and_single_run_at_a_time(ctx):
    client, app, a, base = ctx
    t = client.post(f"/api/apps/{a.id}/perf-tests", json=body(base, profile={"vus": 2, "duration_s": 60})).json()
    run = client.post(f"/api/perf-tests/{t['id']}/run", json={}).json()
    r = client.post(f"/api/perf-tests/{t['id']}/run", json={})
    assert r.status_code == 409 and "sedang berjalan" in r.json()["detail"]
    time.sleep(0.5)
    assert client.post(f"/api/perf-runs/{run['id']}/stop").status_code == 200
    done = wait_done(client, run["id"])
    assert done["status"] == "stopped" and done["result"]["summary"]["duration_s"] < 30


def test_import_curl_splits_secret_headers(ctx):
    client, *_ = ctx
    r = client.post("/api/perf-tests/import-curl", json={
        "text": "curl -X POST 'https://dev.test/api/wo' -H 'Authorization: Bearer abc' -H 'Content-Type: application/json' -d '{\"a\":1}'"})
    data = r.json()
    assert data["request"]["method"] == "POST" and data["request"]["headers"] == {"Content-Type": "application/json"}
    assert data["secret_headers"] == "Authorization: Bearer abc"
    assert client.post("/api/perf-tests/import-curl", json={"text": "wget x"}).status_code == 422


def test_update_keeps_secret_headers_and_delete(ctx):
    client, app, a, base = ctx
    t = client.post(f"/api/apps/{a.id}/perf-tests", json=body(base)).json()
    upd = body(base, name="Ganti nama")
    upd.pop("secret_headers")  # tidak dikirim = tidak diganti
    r = client.patch(f"/api/perf-tests/{t['id']}", json=upd)
    assert r.json()["name"] == "Ganti nama" and r.json()["has_secret_headers"] is True
    assert client.delete(f"/api/perf-tests/{t['id']}").status_code == 204
    assert app.state.secrets.get(f"perf:{t['id']}:headers") is None
