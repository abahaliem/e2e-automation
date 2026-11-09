import json

import pytest
from fastapi.testclient import TestClient

from qa_agent.llm.fake import FakeLLM
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store
from tests.report_fixtures import sample_run
from tests.server.conftest import Brains
from tests.unit.test_skills import make_docx, make_pdf


def test_store_skills_crud_and_selection(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = store.create_skill(name="Standar TC", filename="standar.docx", pages=4, chars=1200, stages=["plan", "report"])
    b = store.create_skill(name="Aturan Cuti", filename="cuti.pdf", pages=7, chars=800, stages=["plan", "judge"], app_ids=[2])
    c = store.create_skill(name="Checklist", filename="cek.md", pages=2, chars=300, stages=["execute"], active=False)
    assert [s.name for s in store.list_skills()] == ["Standar TC", "Aturan Cuti", "Checklist"]
    assert [s.id for s in store.skills_for(app_id=1, stages=("plan", "report"))] == [a.id]
    assert [s.id for s in store.skills_for(app_id=2, stages=("plan", "report"))] == [a.id, b.id]
    assert store.skills_for(app_id=2, stages=("execute", "judge"))[0].id == b.id
    store.update_skill(c.id, active=True, name="Checklist Regresi")
    assert store.get_skill(c.id).active and store.get_skill(c.id).name == "Checklist Regresi"
    store.delete_skill(a.id)
    assert store.get_skill(a.id) is None


@pytest.fixture
def ctx(tmp_path):
    brains = Brains()
    settings = ServerSettings(data_dir=tmp_path / "data")
    app = create_app(settings, secrets=MemorySecretStore(), llm_factory=brains)
    with TestClient(app) as client:
        yield client, settings, brains


def test_skills_api(ctx):
    client, settings, _ = ctx
    body = client.get("/api/skills").json()
    assert body["builtin"]["name"] == "QA Engineer profesional" and len(body["builtin"]["topics"]) == 6
    assert body["skills"] == [] and body["capacity_percent"] >= 1
    r = client.post("/api/skills?filename=standar-test-case.docx", content=make_docx(["Standar Test Case Kantor", "Isi"], pages=4))
    assert r.status_code == 201, r.text
    skill = r.json()
    assert skill["name"] == "Standar Test Case Kantor" and skill["pages"] == 4 and skill["filename"] == "standar-test-case.docx"
    assert skill["stages"] == ["plan", "execute", "judge", "report"] and skill["app_ids"] == [] and skill["active"]
    pdf = client.post("/api/skills?filename=aturan-cuti-lembur.pdf", content=make_pdf(["Aturan Cuti", "Maks 12 hari"])).json()
    assert pdf["pages"] == 1
    app = client.post("/api/apps", json={"name": "Web HR", "url": "http://app.test"}).json()
    r = client.patch(f"/api/skills/{pdf['id']}", json={"stages": ["plan", "judge"], "app_ids": [app["id"]], "name": "Aturan Bisnis Cuti"})
    assert r.json()["app_names"] == ["Web HR"] and r.json()["stages"] == ["plan", "judge"]
    assert "Maks 12 hari" in client.get(f"/api/skills/{pdf['id']}/text").json()["text"]
    assert client.patch(f"/api/skills/{pdf['id']}", json={"stages": ["terbang"]}).status_code == 422
    assert client.post("/api/skills?filename=x.xlsx", content=b"PK").status_code == 422
    assert client.get("/api/skills").json()["capacity_percent"] >= body["capacity_percent"]
    assert client.delete(f"/api/skills/{pdf['id']}").status_code == 204
    assert len(client.get("/api/skills").json()["skills"]) == 1


def test_skill_preview_plans_with_skills(ctx):
    client, settings, brains = ctx
    seen = {}

    def responder(system, messages):
        seen["system"] = system
        return json.dumps({"test_cases": [{"title": "Cuti melebihi 12 hari ditolak", "steps": ["Ajukan cuti 13 hari"],
                                           "expected": "Muncul pesan batas cuti"}]})

    brains.make = lambda profile: FakeLLM(responder)
    client.post("/api/profiles", json={"name": "P", "base_url": "http://x/v1", "model": "m", "api_key": "k"})
    app = client.post("/api/apps", json={"name": "Web HR", "url": "http://app.test"}).json()
    rs = sample_run(settings.runs_dir / "explore")
    meta = rs.read_meta()
    rs.write_meta(meta.model_copy(update={"mode": "explore", "module": None}))
    client.post("/api/import-runs", json={"folder": str(rs.root), "app_id": app["id"]})
    client.post("/api/skills?filename=cuti.md", content="# Aturan Cuti\nCuti tahunan maksimal 12 hari".encode())
    r = client.post("/api/skills/preview", json={"app_id": app["id"], "module": "Pengguna"})
    assert r.status_code == 200, r.text
    assert r.json()["cases"][0]["title"] == "Cuti melebihi 12 hari ditolak"
    assert "## Skill QA" in seen["system"] and "Cuti tahunan maksimal 12 hari" in seen["system"]
    assert client.post("/api/skills/preview", json={"app_id": 999, "module": "X"}).status_code == 404
