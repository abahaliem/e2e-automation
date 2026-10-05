import pytest
from openpyxl import load_workbook

from qa_agent.config import Config
from qa_agent.evidence import RunStore, now_iso
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import QaTestCase, RunMeta
from qa_agent.report.build import build_reports
from qa_agent.runtime import build_runtime, make_explorer, make_planner, make_runner
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.brain import DemoBrain

pytestmark = pytest.mark.browser


@pytest.fixture
def cfg(demo, monkeypatch):
    monkeypatch.setenv("DEMO_USER", DEMO_USER)
    monkeypatch.setenv("DEMO_PASS", DEMO_PASSWORD)
    monkeypatch.setenv("DEMO_AI_KEY", "tidak-dipakai")
    return Config.model_validate({
        "target": {"url": demo.url},
        "accounts": [{"role": "admin", "username_env": "DEMO_USER", "password_env": "DEMO_PASS"}],
        "llm": {"base_url": "http://tidak-dipakai.test/v1", "model": "demo-brain", "api_key_env": "DEMO_AI_KEY"},
        "browser": {"headless": True},
        "limits": {"explore_max_minutes": 5},
    })


def meta(mode, target, module=None, environment="dev"):
    return RunMeta(mode=mode, target=target, environment=environment, model="demo-brain", started_at=now_iso(), module=module)


def run_explore(tmp_path, cfg):
    store = RunStore(tmp_path / "explore")
    store.write_meta(meta("explore", cfg.target.url))
    rt = build_runtime(cfg, store, tmp_path, environment="dev", llm=FakeLLM(DemoBrain()))
    rt.driver.start()
    try:
        app_map = make_explorer(rt).run()
    finally:
        rt.driver.stop()
    return app_map, store


def test_explore_demo_app(tmp_path, cfg, demo):
    app_map, store = run_explore(tmp_path, cfg)
    assert app_map.modules() == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]
    assert app_map.screens[0].public and "/login" in app_map.screens[0].url
    assert sum(1 for s in app_map.screens if s.url.endswith("/edit")) == 1
    assert demo.state.writes == []  # explore tidak pernah submit/hapus/logout
    assert len(demo.state.users) == 2
    xlsx, html = build_reports(store)
    assert "Inventaris Fitur" in load_workbook(xlsx).sheetnames
    assert (tmp_path / ".qa-agent" / "auth").is_dir()
    assert not list(store.root.rglob("*storage*"))  # sesi login tidak disimpan di folder run


def test_deep_dev_finds_seeded_bugs(tmp_path, cfg, demo):
    app_map, _ = run_explore(tmp_path, cfg)
    store = RunStore(tmp_path / "deep")
    store.write_app_map(app_map)
    store.write_meta(meta("deep", cfg.target.url, module="Pengguna"))
    rt = build_runtime(cfg, store, tmp_path, environment="dev", llm=FakeLLM(DemoBrain()))
    cases = make_planner(rt).plan(app_map, "pengguna")
    store.write_testcases(cases)
    rt.driver.start()
    try:
        make_runner(rt).execute(cases, needs_auth=True)
    finally:
        rt.driver.stop()

    assert [c.id for c in cases] == ["TC-PEN-001", "TC-PEN-002", "TC-PEN-003"]
    assert [c.status_ai for c in cases] == ["Pass", "Perlu Review", "Fail"]
    assert len(demo.state.users) == 4  # valid + email tidak valid tersimpan (bug #2); apostrof gagal (bug #1)

    xlsx, html = build_reports(store)
    findings = [row[1] for row in load_workbook(xlsx)["Temuan"].iter_rows(min_row=2, values_only=True)]
    assert findings == ["TC-PEN-002", "TC-PEN-003"]
    assert "HTTP 500 POST" in html.read_text(encoding="utf-8")
    assert DEMO_PASSWORD not in store.steps_path.read_text(encoding="utf-8")


def test_production_mode_blocks_all_writes(tmp_path, cfg, demo):
    store = RunStore(tmp_path / "prod")
    store.write_meta(meta("deep", cfg.target.url, module="Pengguna", environment="production"))
    rt = build_runtime(cfg, store, tmp_path, environment="production", llm=FakeLLM(DemoBrain()))
    cases = [
        QaTestCase(id="TC-PEN-001", module="Pengguna", title="Tambah pengguna dengan data valid",
                   steps=["Isi form", "Klik Simpan"], expected="Tersimpan", start_url=f"{demo.url}/users/new"),
        QaTestCase(id="TC-LAP-001", module="Laporan", title="Proses ulang laporan",
                   steps=["Klik Proses Ulang"], expected="Laporan diproses", start_url=f"{demo.url}/reports"),
    ]
    rt.driver.start()
    try:
        make_runner(rt).execute(cases, needs_auth=True)
    finally:
        rt.driver.stop()

    assert cases[0].status_ai == "Skipped"           # dicegah oleh aturan kata kunci "Simpan"
    assert cases[1].status_ai == "Skipped"           # request diblok di level jaringan (review #4)
    assert demo.state.writes == []                    # tidak ada satu pun request pengubah data yang lolos
    assert len(demo.state.users) == 2
    assert any("/reports/rebuild" in r for r in rt.driver.blocked_requests)  # dicegah di level jaringan
