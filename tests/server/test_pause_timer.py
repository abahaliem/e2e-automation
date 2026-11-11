"""Waktu saat run dijeda tidak dihitung sebagai waktu berjalan."""
from unittest import mock

from qa_agent.server.events import EventHub


def test_paused_time_tracked_in_snapshot_and_events():
    hub = EventHub()
    clock = mock.patch("qa_agent.server.events.time.time")
    with clock as t:
        t.return_value = 1000.0
        hub.publish(1, {"type": "run.status", "status": "running"})
        ev = hub.publish(1, {"type": "control.state", "state": "paused"})
        assert ev["paused_since"] == 1_000_000 and ev["paused_seconds"] == 0
        t.return_value = 1030.0
        ev = hub.publish(1, {"type": "control.state", "state": "running"})
        assert ev["paused_seconds"] == 30 and ev["paused_since"] is None
        t.return_value = 1100.0
        hub.publish(1, {"type": "control.state", "state": "paused"})
        t.return_value = 1110.0
        hub.publish(1, {"type": "run.status", "status": "completed"})  # selesai saat dijeda: jeda ditutup
        snap = hub.snapshot(1)
    assert snap["paused_seconds"] == 40 and snap["paused_since"] is None
