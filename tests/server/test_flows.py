"""Modul kustom (alur bisnis) per aplikasi: dibuat QA, muncul di pilihan Satu modul, dipakai AI menyusun test case."""
import pytest
from fastapi.testclient import TestClient

from qa_agent.evidence import RunStore
from qa_agent.models import AppMap, ScreenInfo
from qa_agent.server.app import create_app
from qa_agent.server.runs import RunRequest, flow_app_map, flow_requirements
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings

FLOW = "1. Buka WO dari daftar Installation\n2. Tap Start lalu Arrive\n3. Isi data dan foto\n4. Close order\nExpected: status CLOSED"
MAP = AppMap(target="android://com.demo.app", screens=[
    ScreenInfo(fingerprint="1", url="android://com.demo.app/Main#a", module="Autentikasi", page_name="Sign In", public=True),
    ScreenInfo(fingerprint="2", url="android://com.demo.app/Main#b", module="Work Order", page_name="Daftar WO"),
    ScreenInfo(fingerprint="3", url="android://com.demo.app/Main#c", module="Riwayat", page_name="History"),
])


@pytest.fixture
def ctx(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="WFM", platform="android", url="android://com.demo.app", allowed_domains=[],
                             login_endpoints=[])
        yield client, app, store, a


def explored(app, store, a):
    rs = RunStore.create(app.state.settings.runs_dir, "explore", "wfm")
    rs.write_app_map(MAP)
    row = store.create_run(app_id=a.id, mode="explore", environment="dev", folder=str(rs.root))
    store.update_run(row.id, status="completed")
    store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")


def test_flow_crud_and_listed_as_module(ctx):
    client, app, store, a = ctx
    explored(app, store, a)
    r = client.post(f"/api/apps/{a.id}/flows", json={"name": "Alur WO sampai Closed", "steps": FLOW})
    assert r.status_code == 201, r.text
    flow = r.json()
    assert flow["name"] == "Alur WO sampai Closed" and flow["steps"] == FLOW
    body = client.get(f"/api/apps/{a.id}/modules").json()
    assert body["modules"] == ["Autentikasi", "Work Order", "Riwayat"]
    assert body["flows"] == [{"id": flow["id"], "name": "Alur WO sampai Closed"}]
    # nama ganda (huruf besar/kecil) dan nama modul hasil penjelajahan ditolak
    assert client.post(f"/api/apps/{a.id}/flows", json={"name": "alur wo sampai closed", "steps": "x"}).status_code == 422
    r = client.post(f"/api/apps/{a.id}/flows", json={"name": "Work Order", "steps": "x"})
    assert r.status_code == 422 and "modul hasil penjelajahan" in r.json()["detail"]
    assert client.post(f"/api/apps/{a.id}/flows", json={"name": "Kosong", "steps": "  "}).status_code == 422
    r = client.patch(f"/api/flows/{flow['id']}", json={"steps": FLOW + "\n5. Cek History"})
    assert r.status_code == 200 and r.json()["steps"].endswith("Cek History")
    assert [f["name"] for f in client.get(f"/api/apps/{a.id}/flows").json()] == ["Alur WO sampai Closed"]
    assert client.delete(f"/api/flows/{flow['id']}").status_code == 204
    assert client.get(f"/api/apps/{a.id}/modules").json()["flows"] == []


def test_flows_are_per_app(ctx):
    client, app, store, a = ctx
    other = store.create_app(name="CMC", platform="web", url="http://cmc.test", allowed_domains=[], login_endpoints=[])
    client.post(f"/api/apps/{a.id}/flows", json={"name": "Alur A", "steps": "langkah"})
    client.post(f"/api/apps/{other.id}/flows", json={"name": "Alur A", "steps": "langkah lain"})  # nama sama boleh di app lain
    assert [f["steps"] for f in client.get(f"/api/apps/{other.id}/flows").json()] == ["langkah lain"]


def test_deep_run_on_flow_uses_flow_as_requirement(ctx):
    client, app, store, a = ctx
    explored(app, store, a)
    flow = client.post(f"/api/apps/{a.id}/flows", json={"name": "Alur WO sampai Closed", "steps": FLOW}).json()
    manager = app.state.manager
    manager._enqueue = lambda run_id: None
    run = manager.submit(RunRequest(app_id=a.id, mode="deep", module="alur wo sampai closed", device_serial="R58M123"))
    assert run.module == "Alur WO sampai Closed"
    assert run.options["flow_id"] == flow["id"]
    assert FLOW in run.options["prd_text"] and "Alur bisnis" in run.options["prd_text"]


def test_flow_map_and_requirements_helpers():
    m = flow_app_map(MAP, "Alur WO")
    assert m.modules() == ["Alur WO"] and len(m.screens_for("Alur WO")) == 3  # alur boleh melintasi semua layar
    assert MAP.modules() == ["Autentikasi", "Work Order", "Riwayat"]  # peta asli tidak berubah
    text = flow_requirements("Alur WO", FLOW, prd="# PRD tambahan")
    assert text.index(FLOW) < text.index("# PRD tambahan")
