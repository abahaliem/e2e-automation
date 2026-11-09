"""Review test case sebelum dijalankan: GET/PUT /api/runs/{id}/plan."""
import pytest
from fastapi.testclient import TestClient

from qa_agent.evidence import RunStore
from qa_agent.models import AppMap, QaTestCase, ScreenInfo
from qa_agent.server.app import create_app
from qa_agent.server.runs import REVIEW_NOTE
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings

SIGNIN = "android://com.demo.app/MainActivity#aaaa"
LEMBUR = "android://com.demo.app/MainActivity#bbbb"


def case(n, title, start=SIGNIN, **kw):
    return QaTestCase(id=f"TC-AUT-00{n}", module="Autentikasi", page="Sign In", title=title, expected="ok",
                      steps=["langkah"], start_url=start, **kw)


@pytest.fixture
def ctx(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="WFM", platform="android", url="android://com.demo.app", allowed_domains=[],
                             login_endpoints=[])
        p = store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")
        rs = RunStore.create(app.state.settings.runs_dir, "deep", "autentikasi")
        rs.write_app_map(AppMap(target="android://com.demo.app", screens=[
            ScreenInfo(fingerprint="1", url=SIGNIN, module="Autentikasi", page_name="Sign In", public=True),
            ScreenInfo(fingerprint="2", url=LEMBUR, module="Autentikasi", page_name="Form Reason Lembur"),
            ScreenInfo(fingerprint="3", url="android://com.demo.app/MainActivity#cccc", module="Order", page_name="Order"),
        ]))
        cases = [case(1, "Sign In valid"), case(2, "Password salah"), case(3, "Submit lembur", LEMBUR)]
        rs.write_testcases(cases)
        row = store.create_run(app_id=a.id, mode="deep", module="Autentikasi", environment="dev", folder=str(rs.root),
                               profile_id=p.id, options={"review_first": True})
        store.upsert_cases(row.id, cases)
        store.update_run(row.id, status="paused", note=REVIEW_NOTE)
        yield client, store, row.id, rs


def test_get_plan_lists_cases_and_module_screens(ctx):
    client, _, run_id, _ = ctx
    body = client.get(f"/api/runs/{run_id}/plan").json()
    assert body["editable"] is True
    assert [c["title"] for c in body["cases"]] == ["Sign In valid", "Password salah", "Submit lembur"]
    assert body["screens"] == [{"url": SIGNIN, "page_name": "Sign In"}, {"url": LEMBUR, "page_name": "Form Reason Lembur"}]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["awaiting_review"] is True


def test_put_plan_edits_deletes_adds_and_renumbers(ctx):
    client, store, run_id, rs = ctx
    cases = client.get(f"/api/runs/{run_id}/plan").json()["cases"]
    keep = {**cases[1], "title": "Password salah (diedit)", "steps": ["Isi username", "Isi password Salah#1"]}
    new = {"title": "Toggle lihat password", "page": "Sign In", "type": "positif", "priority": "Low",
           "precondition": "", "test_data": "", "steps": ["Tap ikon mata"], "expected": "Password terlihat",
           "start_url": SIGNIN}
    r = client.put(f"/api/runs/{run_id}/plan", json={"cases": [keep, new]})
    assert r.status_code == 200, r.text
    saved = rs.read_testcases()
    assert [(c.id, c.title) for c in saved] == [("TC-AUT-001", "Password salah (diedit)"),
                                               ("TC-AUT-002", "Toggle lihat password")]
    assert saved[0].steps == ["Isi username", "Isi password Salah#1"] and saved[1].module == "Autentikasi"
    assert [c.tc_id for c in store.list_cases(run_id)] == ["TC-AUT-001", "TC-AUT-002"]  # indeks ikut bersih


def test_put_plan_validation(ctx):
    client, store, run_id, _ = ctx
    cases = client.get(f"/api/runs/{run_id}/plan").json()["cases"]
    assert client.put(f"/api/runs/{run_id}/plan", json={"cases": []}).status_code == 422
    bad = {**cases[0], "start_url": "android://lain/X#1"}
    r = client.put(f"/api/runs/{run_id}/plan", json={"cases": [bad]})
    assert r.status_code == 422 and "Layar awal" in r.json()["detail"]
    empty = {**cases[0], "title": " ", "steps": []}
    assert client.put(f"/api/runs/{run_id}/plan", json={"cases": [empty]}).status_code == 422
    # Setelah ada test case yang dijalankan, rencana tidak bisa diubah lagi
    store.update_run(run_id, status="completed", note="")
    assert client.get(f"/api/runs/{run_id}/plan").json()["editable"] is False
    r = client.put(f"/api/runs/{run_id}/plan", json={"cases": [cases[0]]})
    assert r.status_code == 409
