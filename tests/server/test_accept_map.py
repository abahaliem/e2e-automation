"""Pemetaan yang terhenti bisa dipakai apa adanya supaya modul dan alur bisnis bisa diuji."""
import pytest
from fastapi.testclient import TestClient

from qa_agent.evidence import RunStore
from qa_agent.models import AppMap, ScreenInfo
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings


@pytest.fixture
def ctx(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="WFM", platform="web", url="http://x.test", allowed_domains=[], login_endpoints=[])

        def make(screens: int, status="interrupted", mode="explore"):
            rs = RunStore.create(app.state.settings.runs_dir, mode, "wfm")
            if screens:
                rs.write_app_map(AppMap(target="x", screens=[
                    ScreenInfo(fingerprint=f"f{i}", url=f"/s{i}", module="Beranda", page_name=f"Layar {i}")
                    for i in range(screens)]))
            row = store.create_run(app_id=a.id, mode=mode, environment="dev", folder=str(rs.root))
            store.update_run(row.id, status=status, note="Server berhenti saat run berjalan")
            return row.id

        yield client, app, a, make


def test_interrupted_map_can_be_used_for_module_tests(ctx):
    client, app, a, make = ctx
    run_id = make(screens=2)
    assert client.get(f"/api/apps/{a.id}/modules").json()["explored"] is False
    r = client.post(f"/api/runs/{run_id}/accept-map")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert "2 layar" in r.json()["note"]
    mods = client.get(f"/api/apps/{a.id}/modules").json()
    assert mods["explored"] is True and mods["modules"] == ["Beranda"]


def test_qa_adds_missing_menu_and_planner_sees_it(ctx):
    from pathlib import Path

    from qa_agent.agent.prompts import plan_message

    client, app, a, make = ctx
    run_id = make(screens=1)
    r = client.patch(f"/api/runs/{run_id}/map/screen",
                     json={"url": "/s0", "qa_actions": ["Customer Information", " customer  information ", "History"]})
    assert r.status_code == 200
    screen = r.json()["modules"][0]["screens"][0]
    assert screen["qa_actions"] == ["Customer Information", "History"]  # duplikat dibuang
    app_map = RunStore(Path(app.state.store.get_run(run_id).folder)).read_app_map()
    text = plan_message(app_map.screens, None).text
    assert "tambahan dari QA" in text and "Customer Information, History" in text
    assert client.patch(f"/api/runs/{run_id}/map/screen", json={"url": "/tidak-ada", "qa_actions": []}).status_code == 404


def test_test_selected_screens_only(ctx):
    """Satu modul, tapi QA memilih layar tertentu saja supaya pengujian lebih cepat."""
    client, app, a, make = ctx
    run_id = make(screens=2, status="completed")
    store = app.state.store
    store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")
    app.state.manager._enqueue = lambda rid: None  # tidak benar-benar menjalankan browser
    mods = client.get(f"/api/apps/{a.id}/modules").json()
    assert [s["page_name"] for s in mods["screens"]["Beranda"]] == ["Layar 0", "Layar 1"]
    r = client.post("/api/runs", json={"app_id": a.id, "mode": "deep", "module": "Beranda", "screens": ["/s1"]})
    assert r.status_code == 201, r.text
    assert r.json()["screen_names"] == ["Layar 1"]
    assert store.get_run(r.json()["id"]).options["screens"] == ["/s1"]
    every = client.post("/api/runs", json={"app_id": a.id, "mode": "deep", "module": "Beranda", "screens": ["/s0", "/s1"]})
    assert every.json()["screen_names"] == []  # semua layar = seluruh modul
    bad = client.post("/api/runs", json={"app_id": a.id, "mode": "deep", "module": "Beranda", "screens": ["/lain"]})
    assert bad.status_code == 422
    assert run_id


def test_accept_map_refused_without_screens_or_while_running(ctx):
    client, app, a, make = ctx
    empty = make(screens=0)
    assert client.post(f"/api/runs/{empty}/accept-map").status_code == 422
    deep = make(screens=1, mode="deep")
    assert client.post(f"/api/runs/{deep}/accept-map").status_code == 422
    running = make(screens=1, status="running")
    app.state.manager.is_active = lambda rid: rid == running
    assert client.post(f"/api/runs/{running}/accept-map").status_code == 409
