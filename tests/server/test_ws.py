import json

import pytest
from fastapi.testclient import TestClient

from qa_agent.agent.control import RunControl
from qa_agent.server.app import create_app
from qa_agent.server.runs import _Active
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.ws import pack_frame, unpack_frame


@pytest.fixture
def ctx(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="X", url="http://app.test")
        run = store.create_run(app_id=a.id, mode="deep", environment="dev", folder=str(tmp_path / "run"),
                               status="running")
        yield client, app, run.id


def step(n):
    return {"type": "step.done", "tc_id": "TC-1", "step_no": n, "result": "ok", "description": f"Langkah {n}"}


def test_pack_frame_roundtrip():
    data = pack_frame(b"\xff\xd8abc", {"width": 1366, "height": 768})
    assert data[:1] == b"F"
    meta, jpeg = unpack_frame(data)
    assert meta == {"width": 1366, "height": 768} and jpeg == b"\xff\xd8abc"


def test_snapshot_first_then_events(ctx):
    client, app, run_id = ctx
    hub = app.state.hub
    hub.publish(run_id, {"type": "run.status", "status": "running"})
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["status"] == "running" and snap["seq"] == 1
        hub.publish(run_id, step(1))
        event = ws.receive_json()
        assert event["type"] == "step.done" and event["seq"] == 2
        hub.publish_frame(run_id, b"\xff\xd8jpeg", {"width": 10, "height": 5})
        meta, jpeg = unpack_frame(ws.receive_bytes())
        assert jpeg == b"\xff\xd8jpeg" and meta["width"] == 10
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_two_clients_same_event(ctx):
    client, app, run_id = ctx
    with client.websocket_connect(f"/ws/runs/{run_id}") as a, client.websocket_connect(f"/ws/runs/{run_id}") as b:
        a.receive_json()
        b.receive_json()
        assert app.state.hub.viewer_count(run_id) == 2
        app.state.hub.publish(run_id, step(1))
        assert a.receive_json() == b.receive_json()


def test_reconnect_snapshot_without_duplicates(ctx):
    client, app, run_id = ctx
    hub = app.state.hub
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        ws.receive_json()
        for n in (1, 2, 3):
            hub.publish(run_id, step(n))
            ws.receive_json()
    hub.publish(run_id, step(4))
    hub.publish(run_id, step(4))  # langkah sama dikirim ulang
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        snap = ws.receive_json()
        ids = [(s["tc_id"], s["step_no"]) for s in snap["steps"]]
        assert ids == [("TC-1", 1), ("TC-1", 2), ("TC-1", 3), ("TC-1", 4)]
        hub.publish(run_id, step(5))
        event = ws.receive_json()
        assert event["step_no"] == 5 and event["seq"] == snap["seq"] + 1


def test_viewers_toggle_streaming(ctx):
    client, app, run_id = ctx
    manager = app.state.manager

    class FakeDriver:
        def __init__(self):
            self.calls = []

        def set_streaming(self, on):
            self.calls.append(on)

    active = _Active(run_id=run_id, control=RunControl(), driver=FakeDriver())
    manager._sync_stream(active)
    assert active.driver.calls == []
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        ws.receive_json()
        manager._sync_stream(active)
        assert active.driver.calls == [True]
    manager._sync_stream(active)
    assert active.driver.calls == [True, False]


def test_global_events(ctx):
    client, app, run_id = ctx
    with client.websocket_connect("/ws/events") as ws:
        app.state.hub.publish_global({"type": "run.status", "run_id": run_id, "status": "completed", "counts": {}})
        event = ws.receive_json()
        assert event["type"] == "run.status" and event["status"] == "completed"


def test_unknown_run_closes(ctx):
    client, *_ = ctx
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/runs/9999") as ws:
            ws.receive_json()
