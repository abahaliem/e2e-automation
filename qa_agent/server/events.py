"""EventHub: snapshot kondisi run + fan-out event/frame ke penonton WebSocket.

`publish` dipanggil dari worker thread; antrian subscriber hidup di event loop asyncio
dan diisi lewat `call_soon_threadsafe`.
"""
from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import Any, Callable

MAX_STEPS = 50
QUEUE_SIZE = 1000
FRAME_BACKLOG = 3
GLOBAL = "*"


class _RunState:
    def __init__(self) -> None:
        self.seq = 0
        self.status = "queued"
        self.control_state = "running"
        self.note = ""
        self.counts: dict[str, int] = {}
        self.current_tc: str | None = None
        self.planned: dict | None = None
        self.steps: OrderedDict[tuple[str, int], dict] = OrderedDict()
        self.cases: OrderedDict[str, dict] = OrderedDict()
        self.screens = 0
        self.asking: dict | None = None  # explorer menunggu jawaban QA: lanjutkan memetakan / selesai

    def apply(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "run.status":
            self.status = event.get("status", self.status)
            self.note = event.get("note", self.note)
            self.counts = event.get("counts", self.counts)
            if self.status != "running":
                self.asking = None
        elif kind == "explore.ask":
            self.asking = {k: event[k] for k in ("screens", "modules", "new_screens") if k in event}
        elif kind == "control.state":
            self.control_state = event.get("state", self.control_state)
            if self.control_state in ("running", "stopped") and event.get("command") != "explore.ask":
                self.asking = None
        elif kind == "tc.started":
            self.current_tc = event["tc_id"]
            self.cases[event["tc_id"]] = {"tc_id": event["tc_id"], "title": event.get("title", ""), "status": None}
        elif kind == "tc.finished":
            entry = self.cases.setdefault(event["tc_id"], {"tc_id": event["tc_id"], "title": "", "status": None})
            entry["status"] = event.get("status")
            if self.current_tc == event["tc_id"]:
                self.current_tc = None
            self.planned = None
        elif kind == "step.planned":
            self.planned = event
        elif kind == "step.done":
            key = (event.get("tc_id", ""), int(event.get("step_no", 0)))
            self.steps.pop(key, None)
            self.steps[key] = event  # id langkah unik: tidak ada duplikat
            while len(self.steps) > MAX_STEPS:
                self.steps.popitem(last=False)
            if self.planned and (self.planned.get("tc_id"), self.planned.get("step_no")) == key:
                self.planned = None
        elif kind == "screen.added":
            self.screens += 1

    def snapshot(self, run_id: Any) -> dict:
        return {
            "type": "snapshot", "run_id": run_id, "seq": self.seq, "status": self.status,
            "control_state": self.control_state, "note": self.note, "counts": self.counts,
            "current_tc": self.current_tc, "planned": self.planned, "steps": list(self.steps.values()),
            "cases": list(self.cases.values()), "screens": self.screens, "asking": self.asking,
        }


class EventHub:
    def __init__(self, on_viewers_changed: Callable[[Any, int], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._states: dict[Any, _RunState] = {}
        self._subs: dict[Any, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self.on_viewers_changed = on_viewers_changed

    def _state(self, run_id: Any) -> _RunState:
        state = self._states.get(run_id)
        if state is None:
            state = self._states[run_id] = _RunState()
        return state

    # ---------- dari worker ----------
    def publish(self, run_id: Any, event: dict) -> dict:
        with self._lock:
            state = self._state(run_id)
            state.seq += 1
            event = {**event, "run_id": run_id, "seq": state.seq}
            state.apply(event)
            subs = list(self._subs.get(run_id, ()))
        for loop, queue in subs:
            self._deliver(loop, queue, event)
        return event

    def publish_global(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs.get(GLOBAL, ()))
        for loop, queue in subs:
            self._deliver(loop, queue, event)

    def publish_frame(self, run_id: Any, jpeg: bytes, meta: dict) -> None:
        with self._lock:
            subs = list(self._subs.get(run_id, ()))
        for loop, queue in subs:
            if queue.qsize() < FRAME_BACKLOG:  # penonton lambat: lewati frame, jangan tumpuk
                self._deliver(loop, queue, ("frame", jpeg, meta))

    @staticmethod
    def _deliver(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, item: Any) -> None:
        def put() -> None:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

        try:
            loop.call_soon_threadsafe(put)
        except RuntimeError:
            pass  # event loop sudah ditutup

    # ---------- snapshot ----------
    def snapshot(self, run_id: Any) -> dict:
        with self._lock:
            state = self._states.get(run_id)
            return (state or _RunState()).snapshot(run_id)

    def forget(self, run_id: Any) -> None:
        with self._lock:
            self._states.pop(run_id, None)

    # ---------- penonton (event loop asyncio) ----------
    def subscribe(self, run_id: Any) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subs.setdefault(run_id, []).append((loop, queue))
            count = len(self._subs[run_id])
        self._viewers_changed(run_id, count)
        return queue

    def unsubscribe(self, run_id: Any, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(run_id, [])
            self._subs[run_id] = [s for s in subs if s[1] is not queue]
            count = len(self._subs[run_id])
        self._viewers_changed(run_id, count)

    def viewer_count(self, run_id: Any) -> int:
        with self._lock:
            return len(self._subs.get(run_id, ()))

    def _viewers_changed(self, run_id: Any, count: int) -> None:
        if run_id != GLOBAL and self.on_viewers_changed is not None:
            self.on_viewers_changed(run_id, count)
