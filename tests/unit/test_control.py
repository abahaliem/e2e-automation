import threading
import time

import pytest

from qa_agent.agent.control import InterventionError, RunControl


def run_in_thread(fn):
    box = {}

    def target():
        box["value"] = fn()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, box


def test_running_passes_through():
    c = RunControl()
    d = c.wait_before_decide(timeout=0.5)
    assert d.kind == "continue"
    d = c.wait_before_execute(timeout=0.5)
    assert d.kind == "continue"


def test_pause_blocks_until_resume():
    c = RunControl()
    c.pause()
    assert c.state == "paused"
    t, box = run_in_thread(lambda: c.wait_before_decide(timeout=3))
    time.sleep(0.2)
    assert "value" not in box
    c.resume()
    t.join(2)
    assert box["value"].kind == "continue"
    assert c.state == "running"


def test_hints_collected_and_drained_once():
    c = RunControl()
    c.hint("Coba menu Pengguna")
    c.hint("Abaikan banner")
    d = c.wait_before_decide(timeout=0.5)
    assert d.hints == ["Coba menu Pengguna", "Abaikan banner"]
    assert c.drain_hints() == []
    c.hint("lagi")
    assert c.drain_hints() == ["lagi"]
    assert c.drain_hints() == []


def test_think_again_when_paused():
    c = RunControl()
    c.pause()
    t, box = run_in_thread(lambda: c.wait_before_execute(timeout=3))
    time.sleep(0.1)
    c.think_again()
    t.join(2)
    assert box["value"].kind == "think_again"
    assert c.state == "running"


def test_think_again_not_paused_rejected():
    c = RunControl()
    with pytest.raises(InterventionError):
        c.think_again()
    assert c.state == "running"


def test_skip():
    c = RunControl()
    c.skip()
    assert c.wait_before_decide(timeout=0.5).kind == "skip"
    # skip hanya berlaku sekali
    assert c.wait_before_decide(timeout=0.5).kind == "continue"


def test_skip_while_paused_unblocks():
    c = RunControl()
    c.pause()
    t, box = run_in_thread(lambda: c.wait_before_decide(timeout=3))
    time.sleep(0.1)
    c.skip()
    t.join(2)
    assert box["value"].kind == "skip"
    assert c.state == "running"


def test_stop_then_commands_rejected():
    c = RunControl()
    c.pause()
    t, box = run_in_thread(lambda: c.wait_before_decide(timeout=3))
    time.sleep(0.1)
    c.stop()
    t.join(2)
    assert box["value"].kind == "stop"
    assert c.state == "stopped"
    assert c.wait_before_execute(timeout=0.5).kind == "stop"
    for cmd in (c.pause, c.resume, c.takeover, c.skip, c.confirm_step):
        with pytest.raises(InterventionError):
            cmd()
    with pytest.raises(InterventionError):
        c.hint("x")


def test_takeover_manual_inputs_in_order():
    c = RunControl()
    c.takeover()
    assert c.state == "takeover"
    c.queue_input({"kind": "click", "x": 0.1, "y": 0.2})
    c.queue_input({"kind": "type", "text": "halo"})
    d1 = c.wait_before_decide(timeout=1)
    d2 = c.wait_before_decide(timeout=1)
    assert (d1.kind, d1.input["kind"]) == ("manual_input", "click")
    assert (d2.kind, d2.input["kind"]) == ("manual_input", "type")
    # tidak ada input: memblok sampai release
    t, box = run_in_thread(lambda: c.wait_before_decide(timeout=3))
    time.sleep(0.1)
    assert "value" not in box
    c.release()
    t.join(2)
    assert box["value"].kind == "continue"
    assert c.state == "running"


def test_queue_input_without_takeover_rejected():
    c = RunControl()
    with pytest.raises(InterventionError):
        c.queue_input({"kind": "click", "x": 0.5, "y": 0.5})
    c.pause()
    with pytest.raises(InterventionError):
        c.queue_input({"kind": "click", "x": 0.5, "y": 0.5})
    assert c.state == "paused"


def test_end_case_only_in_takeover():
    c = RunControl()
    with pytest.raises(InterventionError):
        c.end_case("pass")
    c.takeover()
    with pytest.raises(InterventionError):
        c.end_case("maybe")
    c.end_case("fail", note="Tombol tidak merespons")
    d = c.wait_before_decide(timeout=1)
    assert d.kind == "end_case"
    assert d.end_status == "fail"
    assert d.note == "Tombol tidak merespons"
    assert c.state == "running"


def test_confirm_each_step_blocks_until_confirm():
    c = RunControl(confirm_each_step=True)
    assert c.wait_before_decide(timeout=0.5).kind == "continue"
    t, box = run_in_thread(lambda: c.wait_before_execute(timeout=3))
    time.sleep(0.2)
    assert "value" not in box
    c.confirm_step()
    t.join(2)
    assert box["value"].kind == "continue"
    # konfirmasi berikutnya dibutuhkan lagi
    t2, box2 = run_in_thread(lambda: c.wait_before_execute(timeout=3))
    time.sleep(0.2)
    assert "value" not in box2
    c.confirm_step()
    t2.join(2)
    assert box2["value"].kind == "continue"


def test_confirm_step_rejected_when_not_waiting():
    c = RunControl(confirm_each_step=False)
    with pytest.raises(InterventionError):
        c.confirm_step()


def test_resume_when_running_rejected():
    c = RunControl()
    with pytest.raises(InterventionError):
        c.resume()


def test_idle_called_while_paused():
    c = RunControl()
    calls = []
    c.idle = lambda: calls.append(1)
    c.pause()
    t, box = run_in_thread(lambda: c.wait_before_decide(timeout=3))
    time.sleep(0.5)
    c.resume()
    t.join(2)
    assert box["value"].kind == "continue"
    assert len(calls) >= 2


def test_waiting_flag_for_snapshot():
    c = RunControl(confirm_each_step=True)
    t, _ = run_in_thread(lambda: c.wait_before_execute(timeout=3))
    time.sleep(0.1)
    assert c.awaiting_confirm is True
    c.confirm_step()
    t.join(2)
    assert c.awaiting_confirm is False
