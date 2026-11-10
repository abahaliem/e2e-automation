from datetime import datetime, timedelta

import pytest

from qa_agent.models import QaTestCase
from qa_agent.server.store import Store
from tests.report_fixtures import sample_run


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "qa-agent.db")


def make_app(store, name="HR", platform="web"):
    return store.create_app(name=name, platform=platform, url="http://app.test", allowed_domains=["app.test"],
                            login_endpoints=["/login"])


def case(i, status, final=None, severity=None):
    return QaTestCase(id=f"TC-PEN-{i:03d}", module="Pengguna", title=f"Kasus {i}", expected="x",
                      status_ai=status, status_final=final, severity=severity)


def test_apps_crud(store):
    app = make_app(store)
    assert app.id and app.allowed_domains == ["app.test"] and app.platform == "web"
    assert store.get_app(app.id).name == "HR"
    updated = store.update_app(app.id, name="HR Dev", allowed_domains=["app.test", "cdn.app.test"])
    assert updated.name == "HR Dev" and updated.allowed_domains == ["app.test", "cdn.app.test"]
    assert [a.id for a in store.list_apps()] == [app.id]
    store.delete_app(app.id)
    assert store.get_app(app.id) is None


def test_delete_app_with_runs_rejected(store):
    app = make_app(store)
    store.create_run(app_id=app.id, mode="explore", environment="dev", folder="x")
    with pytest.raises(ValueError):
        store.delete_app(app.id)


def test_accounts(store):
    app = make_app(store)
    acc = store.create_account(app_id=app.id, role="admin", username="qa@app.test")
    assert store.list_accounts(app.id)[0].username == "qa@app.test"
    assert store.get_account(acc.id).role == "admin"
    store.delete_account(acc.id)
    assert store.list_accounts(app.id) == []


def test_profiles_single_default(store):
    p1 = store.create_profile(name="GLM kantor", provider="openai_compat", base_url="http://ai/v1", model="glm",
                              vision=True, timeout_seconds=60, is_default=True)
    p2 = store.create_profile(name="Claude", provider="anthropic", base_url="", model="claude", is_default=True)
    assert store.get_default_profile().id == p2.id
    assert store.get_profile(p1.id).is_default is False
    store.update_profile(p1.id, is_default=True, model="glm-5")
    assert store.get_default_profile().id == p1.id
    assert store.get_profile(p1.id).model == "glm-5"
    assert len(store.list_profiles()) == 2
    store.delete_profile(p1.id)
    assert [p.id for p in store.list_profiles()] == [p2.id]


def test_runs_and_interrupted(store):
    app = make_app(store)
    r1 = store.create_run(app_id=app.id, mode="explore", environment="dev", folder="a")
    assert r1.status == "queued" and r1.counts == {}
    store.update_run(r1.id, status="running", counts={"Pass": 1})
    r2 = store.create_run(app_id=app.id, mode="deep", module="Pengguna", environment="dev", folder="b")
    r3 = store.create_run(app_id=app.id, mode="deep", module="Pengguna", environment="dev", folder="c")
    store.update_run(r3.id, status="completed")
    assert store.get_run(r1.id).counts == {"Pass": 1}
    r4 = store.create_run(app_id=app.id, mode="deep", module="Pengguna", environment="dev", folder="d")
    store.update_run(r4.id, status="paused", note="Menunggu review test case")
    assert store.mark_unfinished_interrupted() == 2
    assert store.get_run(r4.id).status == "paused"  # run dijeda (mis. menunggu review) tidak sedang jalan
    store.delete_run(r4.id)
    assert store.get_run(r1.id).status == "interrupted"
    assert store.get_run(r2.id).status == "interrupted"
    assert store.get_run(r3.id).status == "completed"
    assert [r.id for r in store.list_runs(status="completed")] == [r3.id]
    assert [r.id for r in store.list_runs(app_id=app.id)] == [r3.id, r2.id, r1.id]  # terbaru dulu


def test_cases_upsert_and_findings(store):
    app = make_app(store)
    run = store.create_run(app_id=app.id, mode="deep", module="Pengguna", environment="dev", folder="x")
    store.upsert_cases(run.id, [case(1, "Pass"), case(2, "Perlu Review", severity="Minor")])
    store.upsert_cases(run.id, [case(2, "Perlu Review", final="Fail", severity="Major"), case(3, "Fail")])
    rows = store.list_cases(run.id)
    assert [r.tc_id for r in rows] == ["TC-PEN-001", "TC-PEN-002", "TC-PEN-003"]
    assert rows[1].status_final == "Fail" and rows[1].severity == "Major"
    findings = store.latest_findings(limit=10)
    assert {f["tc_id"] for f in findings} == {"TC-PEN-002", "TC-PEN-003"}
    assert all(f["app_name"] == "HR" and f["status"] == "Fail" for f in findings)


def test_stats(store):
    web = make_app(store)
    android = make_app(store, name="App HP", platform="android")
    now = datetime(2026, 11, 8, 12, 0)
    runs = []
    for i in range(3):
        runs.append(store.create_run(app_id=web.id, mode="deep", environment="dev", folder=f"w{i}",
                                     started_at=(now - timedelta(days=i + 1)).isoformat()))
    runs.append(store.create_run(app_id=android.id, mode="deep", environment="dev", folder="a",
                                 started_at=(now - timedelta(days=2)).isoformat()))
    statuses = ["Pass"] * 7 + ["Fail"] * 2 + ["Skipped"]
    store.upsert_cases(runs[0].id, [case(i, s) for i, s in enumerate(statuses[:5], 1)])
    store.upsert_cases(runs[1].id, [case(i, s) for i, s in enumerate(statuses[5:], 1)])
    # periode sebelumnya: 1 run, 1 Pass dan 1 Fail (status final menggantikan status AI)
    old = store.create_run(app_id=web.id, mode="deep", environment="dev", folder="old",
                           started_at=(now - timedelta(days=45)).isoformat())
    store.upsert_cases(old.id, [case(1, "Pass"), case(2, "Perlu Review", final="Fail")])

    s = store.stats(now - timedelta(days=30), now)
    assert s["total_runs"] == 4 and s["web_runs"] == 3 and s["android_runs"] == 1
    assert s["cases_executed"] == 9
    assert s["fail"] == 2 and s["review"] == 0 and s["findings"] == 2
    assert s["pass_rate"] == pytest.approx(7 / 9)
    assert s["pass_rate_prev"] == pytest.approx(1 / 2)


def test_stats_empty(store):
    s = store.stats(datetime(2026, 1, 1), datetime(2026, 2, 1))
    assert s["total_runs"] == 0 and s["pass_rate"] is None and s["pass_rate_prev"] is None


def test_import_run_folder(store, tmp_path):
    app = make_app(store)
    rs = sample_run(tmp_path / "runs" / "2026-10-05_1430_deep_pengguna")
    run = store.import_run_folder(rs.root, app.id)
    assert run.mode == "deep" and run.module == "Pengguna" and run.status == "completed"
    assert run.folder == str(rs.root)
    assert run.counts == {"Pass": 1, "Perlu Review": 1, "Fail": 1}
    assert len(store.list_cases(run.id)) == 3
    # impor dua kali tidak menggandakan
    again = store.import_run_folder(rs.root, app.id)
    assert again.id == run.id and len(store.list_runs()) == 1


def test_latest_explore_run(store):
    app = make_app(store)
    assert store.latest_completed_explore(app.id) is None
    r = store.create_run(app_id=app.id, mode="explore", environment="dev", folder="e")
    store.update_run(r.id, status="completed")
    assert store.latest_completed_explore(app.id).id == r.id
