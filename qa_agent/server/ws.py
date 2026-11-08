"""WebSocket: /ws/runs/{id} (snapshot, event, frame live) dan /ws/events (status run global).

Kontrol run lewat REST; pesan dari klien diabaikan kecuali {"type": "ping"}.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from qa_agent.server.api.runs import state_snapshot
from qa_agent.server.events import GLOBAL

router = APIRouter()


def pack_frame(jpeg: bytes, meta: dict) -> bytes:
    """b"F" + panjang meta (4 byte big-endian) + meta JSON + JPEG."""
    raw = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    return b"F" + len(raw).to_bytes(4, "big") + raw + jpeg


def unpack_frame(data: bytes) -> tuple[dict, bytes]:
    if data[:1] != b"F":
        raise ValueError("bukan frame")
    size = int.from_bytes(data[1:5], "big")
    return json.loads(data[5:5 + size].decode("utf-8")), data[5 + size:]


async def _serve(ws: WebSocket, topic, first: dict | None) -> None:
    hub = ws.app.state.hub
    queue = hub.subscribe(topic)  # langganan dulu, baru snapshot: event di antaranya dibuang lewat seq
    send_lock = asyncio.Lock()
    try:
        last_seq = 0
        if first is not None:
            snap = first() if callable(first) else first
            last_seq = snap.get("seq", 0)
            await ws.send_json(snap)

        async def pump() -> None:
            while True:
                item = await queue.get()
                async with send_lock:
                    if isinstance(item, tuple):
                        _, jpeg, meta = item
                        await ws.send_bytes(pack_frame(jpeg, meta))
                    else:
                        if topic != GLOBAL and item.get("seq", 0) <= last_seq:
                            continue  # sudah termasuk di snapshot
                        await ws.send_json(item)

        async def receive() -> None:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    async with send_lock:
                        await ws.send_json({"type": "pong"})

        tasks = [asyncio.create_task(pump()), asyncio.create_task(receive())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(topic, queue)


@router.websocket("/ws/runs/{run_id}")
async def run_socket(ws: WebSocket, run_id: int) -> None:
    if ws.app.state.store.get_run(run_id) is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    await _serve(ws, run_id, lambda: state_snapshot(ws.app.state, run_id))


@router.websocket("/ws/events")
async def global_socket(ws: WebSocket) -> None:
    await ws.accept()
    await _serve(ws, GLOBAL, None)
