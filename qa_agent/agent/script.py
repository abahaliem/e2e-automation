"""Skrip regresi: langkah test case yang Pass direkam, lalu diputar ulang tanpa AI.

Putar ulang memakai driver yang sama (web/Android), tetap melewati Safety Guard dan titik kontrol QA
(jeda/hentikan), dan menyimpan screenshot tiap langkah sebagai evidence (pelaku "script").
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field

from qa_agent.agent.control import RunControl
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import Masker, RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.models import Action, Element, Observation, Signal, StepRecord
from qa_agent.orchestrator.fingerprint import normalize_location
from qa_agent.report.humanize import humanize

MAX_EXPECT_TEXTS = 5
END_MATCH_RATIO = 0.6
FIND_ATTEMPTS = 3
_DYNAMIC = re.compile(r"\d{4,}|\d{1,2}[:.]\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")  # tanggal, jam, angka panjang


class ScriptStep(BaseModel):
    action: str | None = None  # click | type | select | scroll | back | wait | navigate
    element: dict | None = None  # {"role", "name", "selector"}
    value: str | None = None
    event: dict | None = None  # input manual QA (Ambil alih)


class TestScript(BaseModel):
    __test__ = False  # bukan kelas test pytest
    version: int = 1
    tc_id: str
    title: str = ""  # judul test case saat direkam; skrip hanya diputar untuk test case yang sama
    steps: list[ScriptStep] = Field(default_factory=list)
    expect_texts: list[str] = Field(default_factory=list)
    end_location: str = ""
    recorded_at: str = Field(default_factory=now_iso)


def _salient(names: list[str], before: list[str]) -> list[str]:
    seen = set(before)
    out: list[str] = []
    for name in names:
        text = (name or "").strip()
        if not text or text in seen or text in out or len(text) > 60 or _DYNAMIC.search(text):
            continue
        out.append(text)
        if len(out) >= MAX_EXPECT_TEXTS:
            break
    return out


def build_script(tc_id: str, trace: dict, masker: Masker | None = None, title: str = "") -> TestScript | None:
    """Skrip dari trace AgentLoop. None bila tidak ada langkah yang bisa diputar ulang."""
    masker = masker or Masker()
    steps: list[ScriptStep] = []
    for raw in trace.get("steps", []):
        if "manual" in raw:
            event = dict(raw["manual"])
            if "text" in event:
                event["text"] = masker.redact(str(event["text"]))
            steps.append(ScriptStep(event=event))
        else:
            steps.append(ScriptStep(action=raw.get("action"), element=raw.get("element"),
                                    value=masker.redact(raw.get("value"))))
    if not steps:
        return None
    return TestScript(tc_id=tc_id, title=title, steps=steps, end_location=trace.get("end_location", ""),
                      expect_texts=_salient(trace.get("end_names", []), trace.get("start_names", [])))


@dataclass
class PlayResult:
    ok: bool
    failed_step: int | None = None  # nomor langkah skrip yang gagal (1..n); None = gagal di pemeriksaan akhir
    reason: str = ""
    signals: list[Signal] = field(default_factory=list)
    steps: int = 0
    interrupted: bool = False
    guard_blocked: bool = False


def _find(obs: Observation, locator: dict) -> Element | None:
    selector, name, role = locator.get("selector"), locator.get("name"), locator.get("role")
    return (next((e for e in obs.elements if selector and e.selector == selector and e.name == name), None)
            or next((e for e in obs.elements if e.role == role and e.name == name), None)
            or next((e for e in obs.elements if selector and e.selector == selector), None))


class ScriptPlayer:
    def __init__(self, *, driver: Driver, guard: Guard, store: RunStore, masker: Masker,
                 control: RunControl | None = None, on_event: Callable[[dict], None] = lambda e: None,
                 sleep: Callable[[float], None] = time.sleep, retry_wait: float = 0.6) -> None:
        self.driver, self.guard, self.store, self.masker = driver, guard, store, masker
        self.control, self.on_event = control, on_event
        self._sleep, self.retry_wait = sleep, retry_wait

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass

    def _record(self, tc_id: str, n: int, obs: Observation, step: ScriptStep, element: Element | None,
                result: str, guard: str = "allowed") -> None:
        shot = self.store.save_screenshot(f"{tc_id}_step-{n:02d}", self.driver.screenshot(
            highlight=element if element is not None and step.action in ("type", "select") else None))
        if obs.evidence:
            self.store.attach_evidence(f"{tc_id}_step-{n:02d}", obs.signals, obs.evidence)
        value = self.masker.mask(step.value)
        description = (humanize("manual", None, "Langkah manual QA (skrip)") if step.event is not None
                       else humanize(step.action or "", step.element, value))
        self.store.append_step(StepRecord(
            tc_id=tc_id, step_no=n, timestamp=now_iso(), location=self.masker.mask(obs.location) or "",
            fingerprint=obs.fingerprint, thought="Diputar ulang dari skrip rekaman (tanpa AI)",
            action=step.action or "manual", element=step.element, value=value, guard=guard,
            result=self.masker.mask(result) or "", signals=obs.signals, screenshot=shot, actor="script"))
        self._emit({"type": "step.done", "tc_id": tc_id, "step_no": n, "result": result, "screenshot": shot,
                    "description": description, "actor": "script"})

    def _stopped(self) -> bool:
        return self.control is not None and self.control.wait_until_running() == "stop"

    def play(self, tc_id: str, script: TestScript) -> PlayResult:
        signals: list[Signal] = []
        obs = self.driver.observe()
        signals.extend(obs.signals)
        for n, step in enumerate(script.steps, 1):
            if self._stopped():
                return PlayResult(ok=False, interrupted=True, reason="Dihentikan oleh QA", signals=signals, steps=n - 1)
            element: Element | None = None
            if step.event is not None:
                manual = getattr(self.driver, "manual_input", None)
                if manual is None:
                    return PlayResult(ok=False, failed_step=n, reason="Driver tidak mendukung langkah manual",
                                      signals=signals, steps=n - 1)
                result = manual(step.event)
            else:
                if step.element:
                    for attempt in range(FIND_ATTEMPTS):
                        element = _find(obs, step.element)
                        if element is not None:
                            break
                        self._sleep(self.retry_wait * (attempt + 1))
                        obs = self.driver.observe()
                        signals.extend(obs.signals)
                    if element is None:
                        name = step.element.get("name") or step.element.get("selector")
                        return PlayResult(ok=False, failed_step=n, signals=signals, steps=n - 1,
                                          reason=f"Langkah {n}: elemen '{name}' tidak ditemukan di layar")
                action = Action(action=step.action or "wait", element=element.index if element else None,  # type: ignore[arg-type]
                                value=step.value)
                decision = self.guard.check(action, element)
                if not decision.allowed:
                    self._record(tc_id, n, obs, step, element, "skipped", guard=f"blocked: {decision.reason}")
                    return PlayResult(ok=False, failed_step=n, signals=signals, steps=n - 1, guard_blocked=True,
                                      reason=f"Langkah {n} diblok Safety Guard: {decision.reason}")
                result = self.driver.execute(action, element)
            if result.fatal:
                raise DriverCrashed(result.error or "Browser tertutup")
            self._record(tc_id, n, obs, step, element, "ok" if result.ok else f"error: {result.error}")
            if not result.ok:
                return PlayResult(ok=False, failed_step=n, signals=signals, steps=n,
                                  reason=f"Langkah {n} gagal: {self.masker.mask(result.error) or ''}")
            obs = self.driver.observe()
            signals.extend(obs.signals)
        if not self._end_matches(obs, script):
            return PlayResult(ok=False, signals=signals, steps=len(script.steps),
                              reason="Semua langkah berjalan, tetapi layar akhir tidak sesuai rekaman "
                                     f"(penanda: {', '.join(script.expect_texts) or script.end_location})")
        return PlayResult(ok=True, signals=signals, steps=len(script.steps))

    @staticmethod
    def _end_matches(obs: Observation, script: TestScript) -> bool:
        if script.expect_texts:
            names = {(e.name or "").strip() for e in obs.elements}
            hits = sum(1 for t in script.expect_texts if t in names)
            return hits / len(script.expect_texts) >= END_MATCH_RATIO
        if script.end_location:
            return normalize_location(obs.location) == normalize_location(script.end_location)
        return True
