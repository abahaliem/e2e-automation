"""RunControl: titik kontrol intervensi QA di agent loop.

Dipanggil dari worker thread (loop) dan dari thread server (perintah).
Semua state dilindungi satu `threading.Condition`.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Literal

IDLE_INTERVAL = 0.15
ControlState = Literal["running", "paused", "takeover", "stopped"]
DecisionKind = Literal["continue", "think_again", "skip", "stop", "end_case", "manual_input"]


class InterventionError(Exception):
    """Perintah intervensi tidak berlaku pada kondisi run saat ini (HTTP 409)."""


@dataclass
class ControlDecision:
    kind: DecisionKind
    hints: list[str] = field(default_factory=list)
    input: dict | None = None
    end_status: str | None = None
    note: str = ""


class RunControl:
    def __init__(self, confirm_each_step: bool = False) -> None:
        self.confirm_each_step = confirm_each_step
        self._cond = threading.Condition()
        self._state: ControlState = "running"
        self._hints: list[str] = []
        self._inputs: deque[dict] = deque()
        self._skip = False
        self._think_again = False
        self._end: tuple[str, str] | None = None
        self._confirmed = False
        self._confirm_expected = False
        self._awaiting_confirm = False
        # Dipanggil berkala dari worker thread selama menunggu (dijeda/ambil alih/konfirmasi).
        self.idle: Callable[[], None] | None = None

    # ---------- properti ----------
    @property
    def state(self) -> ControlState:
        with self._cond:
            return self._state

    @property
    def awaiting_confirm(self) -> bool:
        with self._cond:
            return self._awaiting_confirm

    # ---------- perintah (thread server) ----------
    def _require_alive(self) -> None:
        if self._state == "stopped":
            raise InterventionError("Run sudah dihentikan")

    def pause(self) -> None:
        with self._cond:
            self._require_alive()
            if self._state == "running":
                self._state = "paused"
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._require_alive()
            if self._state == "running":
                raise InterventionError("Run tidak sedang dijeda")
            self._state = "running"
            self._inputs.clear()
            self._cond.notify_all()

    def takeover(self) -> None:
        with self._cond:
            self._require_alive()
            self._state = "takeover"
            self._cond.notify_all()

    def release(self) -> None:
        with self._cond:
            self._require_alive()
            if self._state != "takeover":
                raise InterventionError("Run tidak dalam mode ambil alih")
            self._state = "running"
            self._inputs.clear()
            self._cond.notify_all()

    def hint(self, text: str) -> None:
        text = (text or "").strip()
        with self._cond:
            self._require_alive()
            if not text:
                raise InterventionError("Arahan kosong")
            self._hints.append(text)
            self._cond.notify_all()

    def think_again(self) -> None:
        with self._cond:
            self._require_alive()
            if self._state != "paused":
                raise InterventionError("Pikir ulang hanya bisa saat run dijeda")
            self._think_again = True
            self._state = "running"
            self._cond.notify_all()

    def skip(self) -> None:
        with self._cond:
            self._require_alive()
            self._skip = True
            self._state = "running"
            self._inputs.clear()
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._state = "stopped"
            self._inputs.clear()
            self._cond.notify_all()

    def end_case(self, status: str, note: str = "") -> None:
        with self._cond:
            self._require_alive()
            if self._state != "takeover":
                raise InterventionError("Akhiri test case hanya saat ambil alih")
            if status not in ("pass", "fail"):
                raise InterventionError("Status harus pass atau fail")
            self._end = (status, note or "")
            self._state = "running"
            self._inputs.clear()
            self._cond.notify_all()

    def expect_confirm(self) -> None:
        """Dipanggil loop tepat sebelum mengirim step.planned: konfirmasi QA boleh tiba sebelum worker menunggu."""
        with self._cond:
            if self.confirm_each_step:
                self._confirm_expected = True

    def confirm_step(self) -> None:
        with self._cond:
            self._require_alive()
            if not (self._awaiting_confirm or self._confirm_expected) or self._confirmed:
                raise InterventionError("Tidak ada langkah yang menunggu konfirmasi")
            self._confirmed = True
            self._cond.notify_all()

    def queue_input(self, event: dict) -> None:
        with self._cond:
            self._require_alive()
            if self._state != "takeover":
                raise InterventionError("Input manual hanya diterima saat ambil alih")
            self._inputs.append(dict(event))
            self._cond.notify_all()

    def has_hints(self) -> bool:
        with self._cond:
            return bool(self._hints)

    def drain_hints(self) -> list[str]:
        with self._cond:
            hints, self._hints = self._hints, []
            return hints

    def reset_case(self) -> None:
        """Bersihkan perintah yang khusus untuk satu test case."""
        with self._cond:
            self._skip = False
            self._think_again = False
            self._end = None
            self._confirmed = False
            self._confirm_expected = False

    # ---------- titik kontrol (worker thread) ----------
    def wait_until_running(self) -> Literal["run", "stop"]:
        """Titik kontrol di antara test case: tunggu selama dijeda. Ambil alih/skip diteruskan ke loop."""
        with self._cond:
            while self._state == "paused":
                idle = self.idle
                if idle is None:
                    self._cond.wait()
                    continue
                self._cond.wait(IDLE_INTERVAL)
                self._cond.release()
                try:
                    idle()
                except Exception:
                    pass
                finally:
                    self._cond.acquire()
            return "stop" if self._state == "stopped" else "run"

    def wait_before_decide(self, timeout: float | None = None) -> ControlDecision:
        return self._wait("decide", timeout)

    def wait_before_execute(self, timeout: float | None = None) -> ControlDecision:
        return self._wait("execute", timeout)

    def _wait(self, point: str, timeout: float | None) -> ControlDecision:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            try:
                while True:
                    d = self._ready(point)
                    if d is not None:
                        return d
                    if point == "execute" and self._state == "running":
                        self._awaiting_confirm = True
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("Menunggu titik kontrol terlalu lama")
                    idle = self.idle
                    if idle is None:
                        self._cond.wait(remaining)
                        continue
                    self._cond.wait(IDLE_INTERVAL if remaining is None else min(remaining, IDLE_INTERVAL))
                    # Panggil idle (mis. memproses frame live Playwright) tanpa memegang lock.
                    self._cond.release()
                    try:
                        idle()
                    except Exception:
                        pass
                    finally:
                        self._cond.acquire()
            finally:
                self._awaiting_confirm = False

    def _ready(self, point: str) -> ControlDecision | None:
        if self._state == "stopped":
            return ControlDecision("stop")
        if self._skip:
            self._skip = False
            return ControlDecision("skip")
        if self._end is not None:
            status, note = self._end
            self._end = None
            return ControlDecision("end_case", end_status=status, note=note)
        if self._state == "takeover":
            if self._inputs:
                return ControlDecision("manual_input", input=self._inputs.popleft())
            return None
        if self._think_again:
            self._think_again = False
            return ControlDecision("think_again", hints=self._take_hints())
        if self._state != "running":
            return None
        if point == "execute" and self.confirm_each_step:
            if not self._confirmed:
                return None
            self._confirmed = False
            self._confirm_expected = False
        return ControlDecision("continue", hints=self._take_hints() if point == "decide" else [])

    def _take_hints(self) -> list[str]:
        hints, self._hints = self._hints, []
        return hints
