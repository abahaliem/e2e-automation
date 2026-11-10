import threading
import time

from qa_agent.agent.control import RunControl
from qa_agent.agent.loop import AgentLoop
from qa_agent.evidence import Masker, RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import Signal
from tests.fakes import FakeDriver, act, el, screen, url

HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "button", "Hapus"))
USERS = screen("users", el(1, "link", "Dashboard", href=url("home")))
ERR = screen("err", el(1, "link", "Home"), signals=(Signal(kind="console_error", message="boom"),))


class RecordingDriver(FakeDriver):
    def __init__(self, *a, log: list, **kw):
        super().__init__(*a, **kw)
        self.log = log

    def execute(self, action, element):
        self.log.append(("execute", action.action))
        return super().execute(action, element)


def make(tmp_path, driver, replies, control=None):
    events: list[dict] = []
    store = RunStore(tmp_path / "run")
    llm = FakeLLM(replies)
    loop = AgentLoop(driver=driver, llm=llm, guard=Guard("dev", ["app.test"]), store=store,
                     masker=Masker(["s3cret!"]), data_prefix="QA-AUTO-TEST", control=control,
                     on_event=events.append)
    return loop, llm, store, events


def test_events_order_planned_before_execute(tmp_path):
    log: list = []
    driver = RecordingDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")}, log=log)
    loop, _, _, events = make(tmp_path, driver, [act(action="click", element=1, thought="buka"),
                                                 act(action="done", status="pass", actual="ok")])
    original = loop.on_event
    loop.on_event = lambda e: (log.append(("event", e["type"])), original(e))
    out = loop.run("TC-1", "Buka pengguna")
    assert out.final == "done"
    assert log[:3] == [("event", "step.planned"), ("execute", "click"), ("event", "step.done")]
    planned = [e for e in events if e["type"] == "step.planned"][0]
    assert planned["tc_id"] == "TC-1" and planned["step_no"] == 1
    assert planned["action"] == "click" and planned["thought"] == "buka"
    assert planned["element"]["name"] == "Pengguna" and len(planned["element"]["bbox"]) == 4
    assert planned["description"] == "Klik link 'Pengguna'"
    done = [e for e in events if e["type"] == "step.done"][0]
    assert done["result"] == "ok" and done["screenshot"]


def test_signal_event(tmp_path):
    driver = FakeDriver([ERR], url("err"))
    loop, _, _, events = make(tmp_path, driver, [act(action="done", status="fail", actual="error")])
    loop.run("TC-1", "x")
    sig = [e for e in events if e["type"] == "signal"]
    assert sig and sig[0]["tc_id"] == "TC-1" and sig[0]["signal"]["message"] == "boom"


def test_hint_reaches_prompt_and_log(tmp_path):
    control = RunControl()
    control.hint("Gunakan menu Pengguna")
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    loop, llm, store, _ = make(tmp_path, driver, [act(action="click", element=1),
                                                  act(action="done", status="pass", actual="ok")], control)
    loop.run("TC-1", "x")
    for _, messages in llm.calls:  # arahan berlaku sampai test case selesai
        text = messages[0].text
        assert "## Arahan QA\n- Gunakan menu Pengguna" in text
        assert text.index("## Arahan QA") < text.index("## Layar saat ini")
    steps = store.read_steps()
    hints = [s for s in steps if s.action == "hint"]
    assert len(hints) == 1 and hints[0].value == "Gunakan menu Pengguna" and hints[0].actor == "manual"
    assert all(s.actor == "ai" for s in steps if s.action != "hint")


def test_think_again_discards_plan(tmp_path):
    control = RunControl()
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    calls = {"n": 0}

    def responder(system, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            control.pause()  # QA menjeda setelah AI memutuskan
            threading.Timer(0.1, control.think_again).start()
            return act(action="click", element=2)
        if calls["n"] == 2:
            return act(action="click", element=1)
        return act(action="done", status="pass", actual="ok")

    loop, llm, _, _ = make(tmp_path, driver, responder, control)
    out = loop.run("TC-1", "x")
    assert out.final == "done"
    assert [e[1] for e in driver.executed] == ["Pengguna"]
    assert len(llm.calls) == 3
    assert "Pikir ulang" in llm.calls[1][1][0].text


def test_skip_marks_blocked(tmp_path):
    control = RunControl()
    control.skip()
    driver = FakeDriver([HOME], url("home"))
    loop, llm, _, _ = make(tmp_path, driver, [], control)
    out = loop.run("TC-1", "x")
    assert (out.final, out.error_kind, out.reason) == ("blocked", "skipped_by_qa", "Dilewati oleh QA")
    assert llm.calls == []


def test_stop_interrupted(tmp_path):
    control = RunControl()
    control.stop()
    driver = FakeDriver([HOME], url("home"))
    loop, _, _, _ = make(tmp_path, driver, [], control)
    out = loop.run("TC-1", "x")
    assert out.error_kind == "interrupted"


def test_confirm_each_step_blocks(tmp_path):
    control = RunControl(confirm_each_step=True)
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    loop, _, _, _ = make(tmp_path, driver, [act(action="click", element=1),
                                            act(action="done", status="pass", actual="ok")], control)
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("out", loop.run("TC-1", "x")), daemon=True)
    t.start()
    time.sleep(0.3)
    assert driver.executed == []
    assert control.awaiting_confirm
    control.confirm_step()
    time.sleep(0.3)
    assert len(driver.executed) == 1
    control.confirm_step()  # konfirmasi verdict done
    t.join(3)
    assert box["out"].final == "done"


def test_without_control_unchanged(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    store = RunStore(tmp_path / "run")
    loop = AgentLoop(driver=driver, llm=FakeLLM([act(action="click", element=1), act(action="done", status="pass", actual="ok")]),
                     guard=Guard("dev", ["app.test"]), store=store, masker=Masker([]), data_prefix="X")
    assert loop.run("TC-1", "x").final == "done"


def test_live_frames_keep_flowing_while_ai_thinks(tmp_path):
    """Selama AI berpikir, idle (memproses frame live) tetap dipanggil dari worker thread."""
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    control = RunControl()
    idles = []
    worker = threading.current_thread()
    control.idle = lambda: idles.append(threading.current_thread() is worker)
    loop, llm, _, _ = make(tmp_path, driver, [act(action="done", status="pass", actual="ok")], control=control)
    slow = llm.chat
    llm.chat = lambda system, messages: (time.sleep(0.5), slow(system, messages))[1]
    assert loop.run("TC-1", "x").final == "done"
    assert len(idles) >= 2 and all(idles)  # idle hanya di thread worker (Playwright tidak thread-safe)