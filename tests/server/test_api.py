import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from qa_agent.llm.fake import FakeLLM
from qa_agent.report.excel import TC_HEADERS
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.brain import DemoBrain
from tests.report_fixtures import sample_run
from tests.server.conftest import Brains, wait_for

API_KEY = "sk-abcdef123456"


@pytest.fixture
def ctx(tmp_path):
    settings = ServerSettings(data_dir=tmp_path / "data")
    secrets = MemorySecretStore()
    brains = Brains()
    app = create_app(settings, secrets=secrets, llm_factory=brains)
    with TestClient(app) as client:
        yield client, secrets, brains, settings, app


def make_profile(client, **kw):
    body = {"name": "GLM kantor", "provider": "openai_compatible", "base_url": "http://ai.local/v1",
            "model": "z-ai/glm-5.3-flash", "api_key": API_KEY, "vision": True, "is_default": True, **kw}
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_app(client, url="http://app.test"):
    r = client.post("/api/apps", json={"name": "Web HR", "url": url, "allowed_domains": ["app.test"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_profiles_crud_and_secret_never_returned(ctx):
    client, secrets, *_ = ctx
    p = make_profile(client)
    assert p["api_key_masked"] == "sk-••••3456" and p["has_api_key"] is True
    assert secrets.get(f"ai-profile:{p['id']}") == API_KEY
    listing = client.get("/api/profiles")
    assert API_KEY not in listing.text
    r = client.patch(f"/api/profiles/{p['id']}", json={"model": "glm-5", "api_key": ""})
    assert r.status_code == 200 and r.json()["model"] == "glm-5"
    assert secrets.get(f"ai-profile:{p['id']}") == API_KEY  # string kosong = tidak diganti
    r = client.patch(f"/api/profiles/{p['id']}", json={"api_key": "sk-baru99999999"})
    assert r.json()["api_key_masked"] == "sk-••••9999"
    assert client.delete(f"/api/profiles/{p['id']}").status_code == 204
    assert secrets.get(f"ai-profile:{p['id']}") is None


def test_profile_validation_422(ctx):
    client, *_ = ctx
    r = client.post("/api/profiles", json={"name": "", "provider": "openai_compatible", "model": "m"})
    assert r.status_code == 422
    fields = r.json()["field_errors"]
    assert "name" in fields and "base_url" in fields
    assert fields["base_url"] == "Base URL wajib diisi untuk endpoint OpenAI-compatible"
    r = client.post("/api/profiles", json={"name": "Claude", "provider": "anthropic", "model": "claude"})
    assert r.status_code == 201


def test_profile_test_connection(ctx):
    client, _, brains, *_ = ctx
    p = make_profile(client)
    brains.make = lambda profile: FakeLLM(lambda system, messages: "merah" if messages[0].images else "OK")
    r = client.post(f"/api/profiles/{p['id']}/test")
    body = r.json()
    assert r.status_code == 200 and body["text_ok"] and body["vision_ok"] and body["latency_ms"] >= 0
    brains.make = lambda profile: FakeLLM([])
    body = client.post(f"/api/profiles/{p['id']}/test").json()
    assert body["text_ok"] is False and body["message"]


def test_profile_models_fallback(ctx):
    client, *_ = ctx
    p = make_profile(client, base_url="http://127.0.0.1:9/v1")
    r = client.post(f"/api/profiles/{p['id']}/models")
    assert r.status_code == 200
    assert r.json()["models"] == [] and r.json()["message"]


def test_apps_and_accounts(ctx):
    client, secrets, *_ = ctx
    app = make_app(client)
    assert client.get(f"/api/apps/{app['id']}").json()["name"] == "Web HR"
    r = client.patch(f"/api/apps/{app['id']}", json={"name": "Web HR Dev"})
    assert r.json()["name"] == "Web HR Dev"
    r = client.post(f"/api/apps/{app['id']}/accounts", json={"role": "admin", "username": "qa@app.test",
                                                             "password": "s3cret!"})
    assert r.status_code == 201
    acc = r.json()
    assert "password" not in acc and acc["has_password"] is True
    assert secrets.get(f"account:{acc['id']}") == "s3cret!"
    listing = client.get(f"/api/apps/{app['id']}/accounts")
    assert "s3cret!" not in listing.text and listing.json()[0]["username"] == "qa@app.test"
    r = client.patch(f"/api/accounts/{acc['id']}", json={"password": "baru!"})
    assert r.status_code == 200 and secrets.get(f"account:{acc['id']}") == "baru!"
    assert client.delete(f"/api/accounts/{acc['id']}").status_code == 204
    assert secrets.get(f"account:{acc['id']}") is None
    assert client.get(f"/api/apps/{app['id']}/modules").json() == {"modules": [], "explored": False}
    assert client.delete(f"/api/apps/{app['id']}").status_code == 204
    assert client.get(f"/api/apps/{app['id']}").status_code == 404


def test_app_validation(ctx):
    client, *_ = ctx
    r = client.post("/api/apps", json={"name": "X", "url": "app.test"})
    assert r.status_code == 422 and "url" in r.json()["field_errors"]


def test_run_submit_validation(ctx):
    client, *_ = ctx
    make_profile(client)
    app = make_app(client)
    r = client.post("/api/runs", json={"app_id": app["id"], "mode": "deep", "module": "Pengguna"})
    assert r.status_code == 422 and "Jalankan Seluruh aplikasi dulu" in r.json()["detail"]


def imported_run(client, settings):
    app = make_app(client)
    rs = sample_run(settings.runs_dir / "2026-10-05_1430_deep_pengguna")
    r = client.post("/api/import-runs", json={"folder": str(rs.root), "app_id": app["id"]})
    assert r.status_code == 200 and r.json()["imported"] == 1
    run = client.get("/api/runs").json()[0]
    return run, rs


def test_control_rejected_for_finished_run(ctx):
    client, _, _, settings, _ = ctx
    run, _ = imported_run(client, settings)
    r = client.post(f"/api/runs/{run['id']}/control", json={"command": "pause"})
    assert r.status_code == 409
    r = client.post(f"/api/runs/{run['id']}/control", json={"command": "terbang"})
    assert r.status_code == 422
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 409  # sudah completed


def test_cases_review_patch_updates_reports(ctx):
    client, _, _, settings, _ = ctx
    run, rs = imported_run(client, settings)
    cases = client.get(f"/api/runs/{run['id']}/cases").json()
    assert [c["id"] for c in cases] == ["TC-PEN-001", "TC-PEN-002", "TC-PEN-003"]
    detail = client.get(f"/api/runs/{run['id']}/cases/TC-PEN-003").json()
    assert detail["expected"] == "Tersimpan" and detail["steps"][0]["text"]
    assert detail["steps"][0]["screenshot_url"].startswith(f"/api/runs/{run['id']}/files/screenshots/")
    assert any("HTTP 500" in s for s in detail["technical"])
    r = client.patch(f"/api/runs/{run['id']}/cases/TC-PEN-002",
                     json={"status_final": "Fail", "severity": "Major", "reviewer_note": "Bug valid"})
    assert r.status_code == 200 and r.json()["warning"] is None
    assert r.json()["case"]["status_final"] == "Fail"
    assert json.loads(rs.review_path.read_text(encoding="utf-8"))["TC-PEN-002"]["status_final"] == "Fail"
    ws = load_workbook(rs.report_xlsx)["Test Cases"]
    assert ws.cell(3, TC_HEADERS.index("Status Final") + 1).value == "Fail"
    assert client.get(f"/api/runs/{run['id']}").json()["counts"] == {"Pass": 1, "Fail": 2}
    r = client.patch(f"/api/runs/{run['id']}/cases/TC-PEN-002", json={"status_final": "Lulus"})
    assert r.status_code == 422
    assert client.patch(f"/api/runs/{run['id']}/cases/TC-X", json={"status_final": "Fail"}).status_code == 404


def test_review_saved_when_excel_locked(ctx, monkeypatch):
    client, _, _, settings, _ = ctx
    run, rs = imported_run(client, settings)
    monkeypatch.setattr(Workbook, "save", lambda self, f: (_ for _ in ()).throw(PermissionError(13, "denied")))
    r = client.patch(f"/api/runs/{run['id']}/cases/TC-PEN-002", json={"status_final": "Fail"})
    assert r.status_code == 200
    assert "Tutup report.xlsx" in r.json()["warning"]
    assert json.loads(rs.review_path.read_text(encoding="utf-8"))["TC-PEN-002"]["status_final"] == "Fail"
    assert r.json()["case"]["status_final"] == "Fail"


def test_files_path_traversal(ctx):
    client, _, _, settings, _ = ctx
    run, rs = imported_run(client, settings)
    shot = rs.read_steps()[0].screenshot
    assert client.get(f"/api/runs/{run['id']}/files/{shot}").status_code == 200
    assert client.get(f"/api/runs/{run['id']}/files/../../qa-agent.db").status_code == 404
    assert client.get(f"/api/runs/{run['id']}/files/..%2F..%2Fqa-agent.db").status_code == 404


@pytest.mark.browser
def test_downloads(ctx):
    client, _, _, settings, _ = ctx
    run, _ = imported_run(client, settings)
    r = client.get(f"/api/runs/{run['id']}/download/xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "attachment" in r.headers["content-disposition"]
    r = client.get(f"/api/runs/{run['id']}/download/html")
    assert r.status_code == 200 and b"<html" in r.content.lower()
    r = client.get(f"/api/runs/{run['id']}/download/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert client.get(f"/api/runs/{run['id']}/download/docx").status_code == 404


def test_stats_and_findings(ctx):
    client, _, _, settings, _ = ctx
    imported_run(client, settings)
    s = client.get("/api/stats?days=36500").json()
    assert s["total_runs"] == 1 and s["web_runs"] == 1 and s["findings"] == 2
    assert s["running"] == 0
    findings = client.get("/api/findings?limit=5").json()
    assert {f["tc_id"] for f in findings} == {"TC-PEN-002", "TC-PEN-003"}


def test_spa_fallback(ctx):
    client, _, _, settings, app = ctx
    r = client.get("/dashboard")
    assert r.status_code in (200, 404)
    assert client.get("/api/tidak-ada").status_code == 404


@pytest.mark.browser
def test_live_run_control_409_and_pause(ctx, demo):
    client, secrets, brains, settings, _ = ctx
    gate = threading.Event()

    def slow(profile):
        brain = DemoBrain()

        def respond(system, messages):
            gate.wait(30)
            return brain(system, messages)

        return FakeLLM(respond)

    brains.make = slow
    make_profile(client)
    app = make_app(client, url=demo.url)
    client.patch(f"/api/apps/{app['id']}", json={"allowed_domains": ["127.0.0.1"]})
    acc = client.post(f"/api/apps/{app['id']}/accounts",
                      json={"role": "admin", "username": DEMO_USER, "password": DEMO_PASSWORD}).json()
    r = client.post("/api/runs", json={"app_id": app["id"], "mode": "explore", "account_id": acc["id"]})
    assert r.status_code == 201
    run_id = r.json()["id"]
    wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "running")
    r = client.post(f"/api/runs/{run_id}/control", json={"command": "input", "event": {"kind": "click", "x": 0.5, "y": 0.5}})
    assert r.status_code == 409
    r = client.post(f"/api/runs/{run_id}/control", json={"command": "think_again"})
    assert r.status_code == 409
    r = client.post(f"/api/runs/{run_id}/control", json={"command": "pause"})
    assert r.status_code == 200 and r.json()["state"] == "paused"
    state = client.get(f"/api/runs/{run_id}/state").json()
    assert state["control_state"] == "paused"
    r = client.post(f"/api/runs/{run_id}/control", json={"command": "hint", "text": "Buka menu Laporan"})
    assert r.status_code == 200
    client.post(f"/api/runs/{run_id}/control", json={"command": "resume"})
    gate.set()
    wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "completed")
    assert client.get(f"/api/apps/{app['id']}/modules").json()["modules"] == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]
