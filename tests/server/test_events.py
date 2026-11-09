import asyncio
import threading

from qa_agent.server.events import EventHub


def test_snapshot_after_events():
    hub = EventHub()
    hub.publish(1, {"type": "run.status", "status": "running"})
    hub.publish(1, {"type": "tc.started", "tc_id": "TC-1", "title": "Login"})
    hub.publish(1, {"type": "step.planned", "tc_id": "TC-1", "step_no": 1, "action": "click", "description": "Klik"})
    hub.publish(1, {"type": "step.done", "tc_id": "TC-1", "step_no": 1, "result": "ok", "description": "Klik"})
    hub.publish(1, {"type": "step.done", "tc_id": "TC-1", "step_no": 1, "result": "ok", "description": "Klik"})  # duplikat
    hub.publish(1, {"type": "tc.finished", "tc_id": "TC-1", "status": "Pass"})
    snap = hub.snapshot(1)
    assert snap["status"] == "running"
    assert snap["current_tc"] is None
    assert [(s["tc_id"], s["step_no"]) for s in snap["steps"]] == [("TC-1", 1)]
    assert snap["cases"] == [{"tc_id": "TC-1", "title": "Login", "status": "Pass"}]
    assert snap["seq"] == 6
    assert hub.snapshot(99)["steps"] == []


def test_snapshot_keeps_last_50_steps():
    hub = EventHub()
    for n in range(1, 61):
        hub.publish(1, {"type": "step.done", "tc_id": "TC-1", "step_no": n, "result": "ok"})
    steps = hub.snapshot(1)["steps"]
    assert len(steps) == 50 and steps[0]["step_no"] == 11


def test_two_subscribers_receive_same_event_from_worker_thread():
    hub = EventHub()

    async def scenario():
        q1 = hub.subscribe(1)
        q2 = hub.subscribe(1)
        t = threading.Thread(target=hub.publish, args=(1, {"type": "signal", "tc_id": "TC-1"}))
        t.start()
        t.join()
        e1 = await asyncio.wait_for(q1.get(), 2)
        e2 = await asyncio.wait_for(q2.get(), 2)
        hub.unsubscribe(1, q1)
        hub.unsubscribe(1, q2)
        return e1, e2

    e1, e2 = asyncio.run(scenario())
    assert e1 == e2 and e1["type"] == "signal" and e1["seq"] == 1 and e1["run_id"] == 1


def test_viewer_count_callback_and_frames():
    calls = []
    hub = EventHub(on_viewers_changed=lambda run_id, n: calls.append((run_id, n)))

    async def scenario():
        q = hub.subscribe(5)
        assert hub.viewer_count(5) == 1
        hub.publish_frame(5, b"\xff\xd8jpeg", {"width": 10, "height": 5})
        item = await asyncio.wait_for(q.get(), 2)
        hub.unsubscribe(5, q)
        return item

    item = asyncio.run(scenario())
    assert item == ("frame", b"\xff\xd8jpeg", {"width": 10, "height": 5})
    assert calls == [(5, 1), (5, 0)]
    assert hub.viewer_count(5) == 0


def test_global_topic():
    hub = EventHub()

    async def scenario():
        q = hub.subscribe("*")
        hub.publish_global({"type": "run.status", "run_id": 3, "status": "completed"})
        return await asyncio.wait_for(q.get(), 2)

    assert asyncio.run(scenario())["status"] == "completed"


def test_snapshot_tracks_explore_question():
    from qa_agent.server.events import EventHub

    hub = EventHub()
    hub.publish(1, {"type": "run.status", "status": "running"})
    hub.publish(1, {"type": "explore.ask", "screens": 5, "modules": 3})
    hub.publish(1, {"type": "control.state", "state": "paused", "command": "explore.ask"})
    assert hub.snapshot(1)["asking"] == {"screens": 5, "modules": 3}
    hub.publish(1, {"type": "control.state", "state": "takeover", "command": "takeover"})
    assert hub.snapshot(1)["asking"] is not None  # QA membuka menu sendiri dulu
    hub.publish(1, {"type": "control.state", "state": "running", "command": "release"})
    assert hub.snapshot(1)["asking"] is None