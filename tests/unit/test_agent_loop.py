import pytest

from qa_agent.agent.loop import AgentLoop
from qa_agent.drivers.base import DriverCrashed
from qa_agent.evidence import Masker, RunStore, SECRET_MASK
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import Signal
from tests.fakes import FakeDriver, act, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "button", "Hapus"))
USERS = screen("users", el(1, "link", "Dashboard", href=url("home")))


def make(tmp_path, driver, replies, env="dev", **kw):
    store = RunStore(tmp_path / "run")
    llm = FakeLLM(replies)
    loop = AgentLoop(driver=driver, llm=llm, guard=Guard(env, ["app.test"]), store=store,
                     masker=Masker(["s3cret!"]), data_prefix="QA-AUTO-TEST", **kw)
    return loop, llm, store


def test_click_then_done_pass(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    loop, llm, store = make(tmp_path, driver, [act(action="click", element=1, thought="buka"),
                                              act(action="done", status="pass", actual="Daftar pengguna tampil")])
    out = loop.run("TC-1", "Buka halaman pengguna")
    assert (out.final, out.status, out.actual, out.steps) == ("done", "pass", "Daftar pengguna tampil", 2)
    steps = store.read_steps()
    assert [s.action for s in steps] == ["click", "done"]
    assert steps[0].element["name"] == "Pengguna"
    assert all((store.root / s.screenshot).exists() for s in steps)
    system, messages = llm.calls[0]
    assert system.startswith("MODE: EXECUTE") and "QA-AUTO-TEST" in system
    assert "Buka halaman pengguna" in messages[0].text and messages[0].images


def test_invalid_json_retried_then_recorded(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, store = make(tmp_path, driver, ["bukan json", "masih bukan", act(action="done", status="pass", actual="ok")])
    out = loop.run("TC-1", "x")
    assert out.final == "done"
    assert len(llm.calls) == 3
    assert "tidak valid" in llm.calls[1][1][-1].text
    first = store.read_steps()[0]
    assert first.action == "invalid" and first.result.startswith("error")


def test_production_guard_block_is_reported_to_ai(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, store = make(tmp_path, driver, [act(action="click", element=2), act(action="blocked", reason="aksi diblok")], env="production")
    out = loop.run("TC-1", "Hapus pengguna")
    assert out.final == "blocked" and out.guard_blocks == 1
    assert driver.executed == []
    assert "diblok Safety Guard" in llm.calls[1][1][0].text
    assert store.read_steps()[0].guard.startswith("blocked:")


def test_repeated_action_warns_then_blocks(tmp_path):
    driver = FakeDriver([HOME], url("home"))  # klik tidak mengubah layar
    loop, llm, _ = make(tmp_path, driver, [act(action="click", element=1)] * 4)
    out = loop.run("TC-1", "x")
    assert out.final == "blocked" and out.error_kind == "loop"
    assert "PERINGATAN" in llm.calls[3][1][0].text
    assert len(driver.executed) == 3


def test_max_steps(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users"), (url("users"), "Dashboard"): url("home")})
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="click", element=1)], max_steps=2)
    out = loop.run("TC-1", "x")
    assert out.final == "blocked" and out.error_kind == "max_steps" and out.steps == 2


def test_password_never_reaches_ai_or_logs(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"), {(url("login"), "Masuk"): url("home")})
    driver.set_credentials("qa@app.test", "s3cret!")
    loop, llm, store = make(tmp_path, driver, [
        act(action="type", element=1, value="{{username}}"),
        act(action="type", element=2, value="{{password}}"),
        act(action="click", element=3),
        act(action="done", status="pass", actual="masuk"),
    ])
    out = loop.run("LOGIN-1", "Login", login=True)
    assert out.status == "pass"
    assert ("type", "Password", "s3cret!") in driver.executed
    assert all("s3cret!" not in m.text for _, msgs in llm.calls for m in msgs)
    raw = store.steps_path.read_text(encoding="utf-8")
    assert "s3cret!" not in raw and SECRET_MASK in raw


def test_element_error_is_retried_once(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")}, fail_first=1)
    loop, _, store = make(tmp_path, driver, [act(action="click", element=1), act(action="done", status="pass", actual="ok")])
    loop.run("TC-1", "x")
    assert store.read_steps()[0].result == "ok"
    assert driver.executed == [("click", "Pengguna", None)]


def test_fatal_driver_error_raises(tmp_path):
    driver = FakeDriver([HOME], url("home"), fatal=True)
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1)])
    with pytest.raises(DriverCrashed):
        loop.run("TC-1", "x")


def test_stop_flag_interrupts(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, _ = make(tmp_path, driver, [], should_stop=lambda: True)
    out = loop.run("TC-1", "x")
    assert out.error_kind == "interrupted" and llm.calls == []


def test_relogin_once_when_session_expires(tmp_path):
    driver = FakeDriver([HOME, LOGIN], url("home"), {(url("home"), "Pengguna"): url("login")})
    calls = []

    def relogin(return_to):
        calls.append(return_to)
        driver.current = url("home")

    loop, llm, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="done", status="pass", actual="ok")], relogin=relogin)
    out = loop.run("TC-1", "x")
    assert calls == [url("home")]
    assert "Sesi login kedaluwarsa" in llm.calls[1][1][0].text
    assert out.status == "pass"


def test_relogin_not_repeated(tmp_path):
    driver = FakeDriver([HOME, LOGIN], url("home"), {(url("home"), "Pengguna"): url("login")})
    calls = []
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="blocked", reason="tetap di login")], relogin=calls.append)
    out = loop.run("TC-1", "x")
    assert calls == [url("home")] and out.final == "blocked"


def test_secrets_in_location_signals_and_values_are_masked(tmp_path):
    # Review #6: password bisa muncul di URL (form GET), sinyal, atau value field ("lihat password")
    leaky = screen("akun?password=s3cret!", el(1, "input", "Password", input_type="text", value="s3cret!"),
                   signals=(Signal(kind="http_error", message="HTTP 500", status=500, method="GET", url=url("x?password=s3cret!")),))
    driver = FakeDriver([leaky], leaky.location)
    loop, llm, store = make(tmp_path, driver, [act(action="done", status="fail", actual="password terlihat")])
    loop.run("TC-1", "x")
    assert all("s3cret!" not in m.text for _, msgs in llm.calls for m in msgs)
    assert "s3cret!" not in store.steps_path.read_text(encoding="utf-8")
