"""Skrip regresi: rekam langkah test case yang Pass, putar ulang tanpa AI."""
from qa_agent.agent.control import RunControl
from qa_agent.agent.loop import AgentLoop
from qa_agent.agent.script import ScriptPlayer, TestScript, build_script
from qa_agent.evidence import Masker, RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import Signal
from tests.fakes import FakeDriver, act, el, screen, url

HOME = screen("home", el(1, "link", "Pengguna"), el(2, "text", "Beranda"))
USERS = screen("users", el(1, "textbox", "Nama"), el(2, "button", "Simpan"), el(3, "text", "Daftar Pengguna"),
               el(4, "text", "Total 12 pengguna"))
SAVED = screen("saved", el(1, "text", "Pengguna tersimpan"), el(2, "text", "Daftar Pengguna"),
               el(3, "text", "27-10-2026 09:05"))
FLOW = {(url("home"), "Pengguna"): url("users"), (url("users"), "Simpan"): url("saved")}


def make_loop(tmp_path, driver, replies, secrets=("rahasia-asli",)):
    store = RunStore(tmp_path / "run")
    loop = AgentLoop(driver=driver, llm=FakeLLM(replies), guard=Guard("dev", ["app.test"]), store=store,
                     masker=Masker(list(secrets)), data_prefix="QA-AUTO")
    return loop, store


def test_loop_records_trace_and_script_built_from_pass(tmp_path):
    driver = FakeDriver([HOME, USERS, SAVED], url("home"), FLOW)
    loop, _ = make_loop(tmp_path, driver, [
        act(action="click", element=1),
        act(action="type", element=1, value="QA-AUTO Budi"),
        act(action="click", element=2),
        act(action="done", status="pass", actual="tersimpan"),
    ])
    assert loop.run("TC-1", "tambah pengguna").status == "pass"
    script = build_script("TC-1", loop.last_trace)
    assert [s.action for s in script.steps] == ["click", "type", "click"]
    assert script.steps[0].element == {"role": "link", "name": "Pengguna", "selector": "link:Pengguna"}
    assert script.steps[1].value == "QA-AUTO Budi"
    # penanda akhir: teks yang baru muncul di layar akhir; tanggal (angka panjang) dibuang
    assert script.expect_texts == ["Pengguna tersimpan", "Daftar Pengguna"]
    assert script.end_location == url("saved")


def test_script_never_contains_real_password(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, _ = make_loop(tmp_path, driver, [])
    trace = {"steps": [{"action": "type", "element": {"role": "textbox", "name": "Password", "selector": "p"},
                        "value": "{{password}}"},
                       {"manual": {"kind": "type", "text": "rahasia-asli"}}],
             "start_names": [], "end_names": ["Beranda"], "end_location": url("home")}
    script = build_script("TC-1", trace, masker=Masker(["rahasia-asli"]))
    assert "rahasia-asli" not in script.model_dump_json()
    assert script.steps[1].event == {"kind": "type", "text": "{{password}}"}


def player(tmp_path, driver, **kw):
    store = RunStore(tmp_path / "replay")
    return ScriptPlayer(driver=driver, guard=Guard(kw.pop("env", "dev"), ["app.test"]), store=store,
                        masker=Masker([]), **kw), store


def recorded():
    return TestScript.model_validate({
        "tc_id": "TC-1", "end_location": url("saved"), "expect_texts": ["Pengguna tersimpan", "Daftar Pengguna"],
        "steps": [
            {"action": "click", "element": {"role": "link", "name": "Pengguna", "selector": "link:Pengguna"}},
            {"action": "type", "element": {"role": "textbox", "name": "Nama", "selector": "textbox:Nama"}, "value": "QA-AUTO Budi"},
            {"action": "click", "element": {"role": "button", "name": "Simpan", "selector": "button:Simpan"}},
        ]})


def test_replay_passes_without_ai(tmp_path):
    driver = FakeDriver([HOME, USERS, SAVED], url("home"), FLOW)
    p, store = player(tmp_path, driver)
    result = p.play("TC-1", recorded())
    assert result.ok and result.failed_step is None
    assert driver.current == url("saved")
    assert [s.actor for s in store.read_steps()] == ["script"] * 3  # evidence tetap ada
    assert all(s.screenshot for s in store.read_steps())


def test_replay_reports_missing_element(tmp_path):
    renamed = screen("home", el(1, "link", "Kelola Pengguna"))  # tombol berganti nama
    driver = FakeDriver([renamed, USERS, SAVED], url("home"), FLOW)
    p, _ = player(tmp_path, driver)
    result = p.play("TC-1", recorded())
    assert not result.ok and result.failed_step == 1
    assert "Pengguna" in result.reason and "tidak ditemukan" in result.reason


def test_replay_end_check_mismatch(tmp_path):
    other = screen("saved", el(1, "text", "Gagal menyimpan"))
    driver = FakeDriver([HOME, USERS, other], url("home"), FLOW)
    p, _ = player(tmp_path, driver)
    result = p.play("TC-1", recorded())
    assert not result.ok and result.failed_step is None and "layar akhir" in result.reason


def test_replay_respects_guard_in_production(tmp_path):
    script = recorded()
    script.steps[2].element = {"role": "button", "name": "Hapus", "selector": "button:Hapus"}
    users = screen("users", el(1, "textbox", "Nama"), el(2, "button", "Hapus"))
    driver = FakeDriver([HOME, users], url("home"), {(url("home"), "Pengguna"): url("users")})
    p, _ = player(tmp_path, driver, env="production")
    result = p.play("TC-1", script)
    assert not result.ok and result.failed_step == 3 and "Safety Guard" in result.reason
    assert result.guard_blocked


def test_replay_collects_error_signals(tmp_path):
    saved = screen("saved", el(1, "text", "Pengguna tersimpan"), el(2, "text", "Daftar Pengguna"),
                   signals=(Signal(kind="http_error", message="500", status=500),))
    driver = FakeDriver([HOME, USERS, saved], url("home"), FLOW)
    p, _ = player(tmp_path, driver)
    result = p.play("TC-1", recorded())
    assert result.ok and any(s.status == 500 for s in result.signals)


def test_replay_stops_when_run_stopped(tmp_path):
    control = RunControl()
    control.stop()
    driver = FakeDriver([HOME, USERS, SAVED], url("home"), FLOW)
    p, _ = player(tmp_path, driver, control=control)
    result = p.play("TC-1", recorded())
    assert result.interrupted and driver.current == url("home")
