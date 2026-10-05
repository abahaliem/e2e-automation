from datetime import datetime

from qa_agent.evidence import Masker, RunStore, SECRET_MASK, module_abbr, slugify
from qa_agent.models import AppMap, QaTestCase, RunMeta, ScreenInfo, StepRecord


def step(tc, n, **kw):
    return StepRecord(tc_id=tc, step_no=n, timestamp="2026-10-05T10:00:00", action="click", **kw)


def test_slugify():
    assert slugify("Manajemen Pengguna — Ä") == "manajemen-pengguna-a"
    assert slugify("app-dev.kantor.local:8080") == "app-dev-kantor-local-8080"
    assert slugify("!!!") == "run"


def test_module_abbr():
    assert module_abbr("Pengguna") == "PEN"
    assert module_abbr("Manajemen User") == "MU"
    assert module_abbr("Laporan Keuangan Bulanan Tahunan Detail") == "LKBT"
    assert module_abbr("—") == "TC"


def test_create_names_and_collision(tmp_path):
    runs = tmp_path / "folder dengan spasi" / "runs"
    now = datetime(2026, 10, 5, 14, 30)
    a = RunStore.create(runs, "deep", "Manajemen Pengguna", now=now)
    b = RunStore.create(runs, "deep", "Manajemen Pengguna", now=now)
    assert a.root.name == "2026-10-05_1430_deep_manajemen-pengguna"
    assert b.root.name == "2026-10-05_1430_deep_manajemen-pengguna-2"
    assert a.screenshots_dir.is_dir()


def test_screenshot_relative_path(tmp_path):
    store = RunStore(tmp_path / "run")
    rel = store.save_screenshot("TC-1_step-01", b"png")
    assert rel == "screenshots/TC-1_step-01.png"
    assert (store.root / rel).read_bytes() == b"png"


def test_steps_roundtrip_unicode_and_truncated_line(tmp_path):
    store = RunStore(tmp_path / "run ä")
    store.append_step(step("TC-1", 1, value="Nama 😀 — Ä"))
    store.append_step(step("TC-1", 2))
    with store.steps_path.open("a", encoding="utf-8") as f:
        f.write('{"tc_id": "TC-1", "step_no": 3, "time')  # baris terpotong saat crash
    steps = store.read_steps()
    assert [s.step_no for s in steps] == [1, 2]
    assert steps[0].value == "Nama 😀 — Ä"


def test_drop_steps(tmp_path):
    store = RunStore(tmp_path / "run")
    store.append_step(step("TC-1", 1))
    store.append_step(step("TC-2", 1))
    store.append_step(step("TC-1", 2))
    store.drop_steps("TC-1")
    assert [(s.tc_id, s.step_no) for s in store.read_steps()] == [("TC-2", 1)]


def test_json_roundtrips(tmp_path):
    store = RunStore(tmp_path / "run")
    assert store.read_testcases() == [] and store.read_app_map() is None and store.read_review() == {}
    cases = [QaTestCase(id="TC-PEN-001", module="Pengguna", title="Tambah — valid", expected="Tersimpan")]
    store.write_testcases(cases)
    assert store.read_testcases() == cases
    app_map = AppMap(target="http://a", screens=[ScreenInfo(fingerprint="f", url="http://a/", module="Dashboard", page_name="Beranda")])
    store.write_app_map(app_map)
    assert store.read_app_map() == app_map
    meta = RunMeta(mode="deep", target="http://a", environment="dev", model="m", started_at="2026-10-05T10:00:00")
    store.write_meta(meta)
    assert store.read_meta() == meta
    store.write_review({"TC-PEN-001": {"status_final": "Fail", "reviewer_note": "cek"}})
    assert store.read_review()["TC-PEN-001"]["status_final"] == "Fail"


def test_masker():
    m = Masker(["s3cret!", ""])
    assert m.mask("password s3cret! salah") == f"password {SECRET_MASK} salah"
    assert m.mask("isi {{password}}") == f"isi {SECRET_MASK}"
    assert m.mask("{{username}}") == "{{username}}"
    assert m.mask(None) is None
