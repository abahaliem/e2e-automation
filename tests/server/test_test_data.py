"""Data uji per aplikasi ({{data:nama}}) dan persiapan HTTP sebelum run / test case."""
import json

import pytest
from fastapi.testclient import TestClient

from qa_agent.models import QaTestCase
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store
from qa_agent.server.testdata import (DataPreparer, HookError, apply_values, data_hint, extract, placeholders,
                                      run_hook)


def tc(**kw):
    kw.setdefault("title", "Tutup WO {{data:wo_id}}")
    kw.setdefault("steps", ["Buka WO {{data:wo_id}}", "Isi catatan {{data:catatan}}", "Tap Close"])
    kw.setdefault("expected", "WO {{data:wo_id}} CLOSED")
    return QaTestCase(id="TC-ALU-001", module="Alur WO", **kw)


def test_placeholders_and_apply_same_value_per_case():
    case = tc(test_data="WO: {{data:wo_id}}")
    assert placeholders(case) == ["wo_id", "catatan"]
    apply_values(case, {"wo_id": "000090014541", "catatan": "QA-AUTO selesai"})
    assert case.title == "Tutup WO 000090014541"
    assert case.steps[0] == "Buka WO 000090014541" and case.test_data == "WO: 000090014541"
    assert case.expected == "WO 000090014541 CLOSED" and placeholders(case) == []


def test_store_allocates_each_value_once(tmp_path):
    store = Store(tmp_path / "db")
    a = store.create_app(name="WFM", platform="android", url="android://com.x.y")
    store.add_test_data(a.id, "wo_id", ["111", "222", " ", "111"])  # kosong & duplikat diabaikan
    assert [v.value for v in store.list_test_data(a.id)] == ["111", "222"]
    assert store.take_test_data(a.id, "WO_ID", "run 5 / TC-1") == "111"  # nama tidak peka huruf besar
    assert store.take_test_data(a.id, "wo_id", "run 5 / TC-2") == "222"
    assert store.take_test_data(a.id, "wo_id", "run 5 / TC-3") is None  # habis
    used = store.list_test_data(a.id)[0]
    assert used.used_by == "run 5 / TC-1" and used.used_at
    store.reset_test_data(used.id)
    assert store.take_test_data(a.id, "wo_id", "run 6") == "111"


def test_preparer_allocates_or_blocks(tmp_path):
    store = Store(tmp_path / "db")
    a = store.create_app(name="WFM", platform="android", url="android://com.x.y")
    store.add_test_data(a.id, "wo_id", ["111"])
    prep = DataPreparer(store, MemorySecretStore(), app_id=a.id, run_id=7)
    case = tc(steps=["Buka WO {{data:wo_id}}"], expected="CLOSED")
    assert prep(case) is None and case.steps == ["Buka WO 111"]
    case2 = tc(steps=["Buka WO {{data:wo_id}}"], expected="CLOSED")
    problem = prep(case2)
    assert problem and "Data uji 'wo_id' habis" in problem and "Aplikasi" in problem
    assert case2.steps == ["Buka WO {{data:wo_id}}"]  # tidak diubah bila gagal


class FakeHttp:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.calls = status, body if body is not None else {"data": {"id": "WO-999"}}, []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        return self.status, json.dumps(self.body).encode()


def test_run_hook_captures_value_and_resolves_placeholders(tmp_path):
    store = Store(tmp_path / "db")
    a = store.create_app(name="WFM", platform="android", url="android://com.x.y")
    store.add_test_data(a.id, "teknisi", ["T-01"])
    secrets = MemorySecretStore()
    hook = store.create_hook(app_id=a.id, name="Buat WO uji", when="case", method="POST",
                             url="https://dev.test/api/wo", body='{"teknisi": "{{data:teknisi}}"}',
                             capture={"wo_id": "data.id"})
    secrets.set(f"hook:{hook.id}:headers", json.dumps({"Authorization": "Bearer rahasia"}))
    http = FakeHttp()
    captured = run_hook(store, secrets, hook, used_by="run 7", http=http)
    assert captured == {"wo_id": "WO-999"}
    method, url, headers, body = http.calls[0]
    assert method == "POST" and headers["Authorization"] == "Bearer rahasia"
    assert json.loads(body) == {"teknisi": "T-01"}
    assert [v.value for v in store.list_test_data(a.id) if v.set_name == "wo_id"] == ["WO-999"]
    assert next(v for v in store.list_test_data(a.id) if v.set_name == "teknisi").used_by is None  # hanya dibaca
    with pytest.raises(HookError, match="HTTP 500"):
        run_hook(store, secrets, hook, used_by="run 7", http=FakeHttp(status=500))
    with pytest.raises(HookError, match="data.id"):
        run_hook(store, secrets, hook, used_by="run 7", http=FakeHttp(body={"x": 1}))


def test_case_hook_runs_before_allocation(tmp_path):
    store = Store(tmp_path / "db")
    a = store.create_app(name="WFM", platform="android", url="android://com.x.y")
    store.create_hook(app_id=a.id, name="Buat WO", when="case", method="POST", url="https://dev.test/wo",
                      capture={"wo_id": "data.id"})
    prep = DataPreparer(store, MemorySecretStore(), app_id=a.id, run_id=7, http=FakeHttp())
    case = tc(steps=["Buka WO {{data:wo_id}}"], expected="CLOSED")
    assert prep(case) is None and case.steps == ["Buka WO WO-999"]  # WO baru dibuat lalu langsung dipakai


def test_extract_and_hint():
    assert extract({"data": {"items": [{"id": 5}]}}, "data.items.0.id") == "5"
    assert extract({"a": 1}, "b") is None
    hint = data_hint({"wo_id": ["111", "222"], "catatan": []})
    assert "{{data:wo_id}}" in hint and "111" in hint and "catatan" in hint


# ---------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as c:
        a = app.state.store.create_app(name="WFM", platform="android", url="android://com.x.y")
        yield c, app, a


def test_test_data_api(client):
    c, _, a = client
    r = c.post(f"/api/apps/{a.id}/test-data", json={"name": "wo_id", "values": "000090014541\n000090014542\n"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body[0]["name"] == "wo_id" and body[0]["available"] == 2
    assert [v["value"] for v in body[0]["values"]] == ["000090014541", "000090014542"]
    assert c.post(f"/api/apps/{a.id}/test-data", json={"name": "wo id!", "values": "x"}).status_code == 422
    vid = body[0]["values"][0]["id"]
    assert c.delete(f"/api/test-data/{vid}").status_code == 204
    assert c.delete(f"/api/apps/{a.id}/test-data/wo_id").status_code == 204
    assert c.get(f"/api/apps/{a.id}/test-data").json() == []


def test_hooks_api_keeps_headers_secret(client):
    c, app, a = client
    r = c.post(f"/api/apps/{a.id}/hooks", json={
        "name": "Buat WO uji", "when": "case", "method": "POST", "url": "https://dev.test/api/wo",
        "headers": '{"Authorization": "Bearer rahasia-123"}', "body": "{}", "capture": "wo_id=data.id"})
    assert r.status_code == 201, r.text
    hook = r.json()
    assert hook["capture"] == {"wo_id": "data.id"} and hook["has_headers"] is True
    assert "rahasia-123" not in json.dumps(c.get(f"/api/apps/{a.id}/hooks").json())
    assert app.state.secrets.get(f"hook:{hook['id']}:headers")
    bad = c.post(f"/api/apps/{a.id}/hooks", json={"name": "x", "when": "case", "method": "POST", "url": "ftp://x",
                                                  "headers": "", "body": "", "capture": ""})
    assert bad.status_code == 422
    assert c.patch(f"/api/hooks/{hook['id']}", json={"active": False}).json()["active"] is False
    assert c.delete(f"/api/hooks/{hook['id']}").status_code == 204
    assert app.state.secrets.get(f"hook:{hook['id']}:headers") is None


def test_planner_gets_available_test_data_hint(client):
    c, app, a = client
    store = app.state.store
    store.add_test_data(a.id, "wo_id", ["000090014541", "000090014542"])
    store.take_test_data(a.id, "wo_id", "run 1")
    row = store.create_run(app_id=a.id, mode="deep", module="Alur WO", environment="dev", folder="x")
    skills = app.state.manager._skills_with_data(row)
    assert "{{data:wo_id}}" in skills["plan"] and "1 nilai tersedia" in skills["plan"]
    assert "000090014541" not in skills["plan"]  # yang sudah terpakai tidak ditawarkan