import threading
import time

from qa_agent.agent.control import RunControl
from qa_agent.agent.loop import AgentLoop
from qa_agent.evidence import Masker, RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import ActionResult
from tests.fakes import FakeDriver, act, el, screen, url

HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "button", "Hapus"))
USERS = screen("users", el(1, "link", "Dashboard", href=url("home")))


def make(tmp_path, driver, replies, control):
    store = RunStore(tmp_path / "run")
    llm = FakeLLM(replies)
    events: list[dict] = []
    loop = AgentLoop(driver=driver, llm=llm, guard=Guard("production", ["app.test"]), store=store,
                     masker=Masker(["s3cret!"]), data_prefix="QA-AUTO-TEST", control=control, on_event=events.append)
    return loop, llm, store, events


def run_bg(loop):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("out", loop.run("TC-1", "x")), daemon=True)
    t.start()
    return t, box


def test_takeover_inputs_then_release_ai_gets_note(tmp_path):
    control = RunControl()
    control.takeover()
    driver = FakeDriver([HOME, USERS], url("home"))
    loop, llm, store, events = make(tmp_path, driver, [act(action="done", status="pass", actual="ok")], control)
    t, box = run_bg(loop)
    control.queue_input({"kind": "click", "x": 0.42, "y": 0.31})
    control.queue_input({"kind": "type", "text": "s3cret!"})
    time.sleep(0.3)
    assert [e["kind"] for e in driver.manual] == ["click", "type"]
    assert llm.calls == []
    control.release()
    t.join(3)
    assert box["out"].final == "done"
    steps = store.read_steps()
    manual = [s for s in steps if s.actor == "manual"]
    assert manual[0].value.startswith("Klik di area (0.42, 0.31)") and manual[1].value == "Ketik 7 karakter"
    assert all(s.action == "manual" and s.screenshot for s in manual)
    assert "s3cret!" not in (tmp_path / "run" / "steps.jsonl").read_text(encoding="utf-8")
    text = llm.calls[0][1][0].text
    assert "QA melakukan langkah manual" in text and "Klik di area (0.42, 0.31)" in text
    assert any(e["type"] == "step.done" and e["actor"] == "manual" for e in events)


def test_manual_click_named_by_element_and_screen_change():
    from qa_agent.agent.loop import describe_manual, element_at
    from qa_agent.models import Element, Observation

    menu = Element(index=1, role="link", name="GGC Report  Mapping", bbox=(40, 290, 200, 20))
    sidebar = Element(index=2, role="navigation", name="Menu", bbox=(0, 0, 260, 800))
    obs = Observation(url="https://app.test/", title="t", location="Dashboard", elements=[sidebar, menu], fingerprint="a")
    size = {"width": 1000, "height": 800}
    hit = element_at(obs, {"kind": "click", "x": 0.1, "y": 0.375}, size)  # (100, 300) di dalam menu & sidebar
    assert hit is menu  # elemen terkecil yang memuat titik
    assert describe_manual({"kind": "click"}, Masker([]), hit) == "Klik 'GGC Report Mapping'"
    assert element_at(obs, {"kind": "click", "x": 0.9, "y": 0.9}, size) is None


def test_manual_click_bypasses_keyword_guard(tmp_path):
    # Guard kata kunci (mis. "Hapus" di production) tidak berlaku untuk klik manusia.
    control = RunControl()
    control.takeover()
    driver = FakeDriver([HOME], url("home"))
    loop, _, _, _ = make(tmp_path, driver, [], control)
    t, box = run_bg(loop)
    control.queue_input({"kind": "click", "x": 0.9, "y": 0.1})
    time.sleep(0.2)
    control.end_case("fail", note="Tombol Hapus tidak bereaksi")
    t.join(3)
    out = box["out"]
    assert len(driver.manual) == 1
    assert (out.final, out.status, out.error_kind) == ("done", "fail", "ended_by_qa")
    assert out.actual == "Diverifikasi manual oleh QA: Tombol Hapus tidak bereaksi"


def test_end_case_pass(tmp_path):
    control = RunControl()
    control.takeover()
    control.end_case("pass")
    driver = FakeDriver([HOME], url("home"))
    loop, _, _, _ = make(tmp_path, driver, [], control)
    out = loop.run("TC-1", "x")
    assert (out.status, out.actual, out.error_kind) == ("pass", "Diverifikasi manual oleh QA", "ended_by_qa")


def test_manual_input_failure_recorded(tmp_path):
    control = RunControl()
    control.takeover()
    driver = FakeDriver([HOME], url("home"))
    driver.manual_result = ActionResult(ok=False, error="di luar layar")
    loop, _, store, _ = make(tmp_path, driver, [], control)
    t, box = run_bg(loop)
    control.queue_input({"kind": "key", "key": "Enter"})
    time.sleep(0.2)
    control.end_case("pass")
    t.join(3)
    rec = [s for s in store.read_steps() if s.actor == "manual"][0]
    assert rec.value == "Tekan tombol Enter" and rec.result.startswith("error")
