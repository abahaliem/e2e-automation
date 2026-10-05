from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from qa_agent.agent import prompts
from qa_agent.agent.loop_detect import LoopDetector
from qa_agent.agent.parser import ActionParseError, parse_action
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import Masker, RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient, Message
from qa_agent.models import Action, Element, Observation, Signal, StepRecord
from qa_agent.report.humanize import humanize

HISTORY_WINDOW = 8


@dataclass
class LoopOutcome:
    final: Literal["done", "blocked"]
    status: Literal["pass", "fail"] | None = None
    actual: str = ""
    reason: str = ""
    severity: str | None = None
    steps: int = 0
    guard_blocks: int = 0
    signals: list[Signal] = field(default_factory=list)
    error_kind: str = ""  # "", "max_steps", "loop", "interrupted", "agent"


def find_same(obs: Observation, element: Element) -> Element | None:
    for e in obs.elements:
        if e.selector and e.selector == element.selector:
            return e
    for e in obs.elements:
        if e.role == element.role and e.name == element.name:
            return e
    return None


def _element_dict(element: Element | None) -> dict[str, str] | None:
    if element is None:
        return None
    return {"role": element.role, "name": element.name, "selector": element.selector}


class AgentLoop:
    def __init__(
        self,
        *,
        driver: Driver,
        llm: LLMClient,
        guard: Guard,
        store: RunStore,
        masker: Masker,
        data_prefix: str,
        platform: str = "web",
        max_steps: int = 25,
        vision: bool = True,
        relogin: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.driver = driver
        self.llm = llm
        self.guard = guard
        self.store = store
        self.masker = masker
        self.data_prefix = data_prefix
        self.platform = platform
        self.max_steps = max_steps
        self.vision = vision
        self.relogin = relogin
        self.should_stop = should_stop

    def run(self, tc_id: str, goal: str, *, allow_logout: bool = False, login: bool = False) -> LoopOutcome:
        system = prompts.execute_system(self.platform, self.data_prefix)
        history: list[str] = []
        notes: list[str] = []
        signals: list[Signal] = []
        detector = LoopDetector()
        guard_blocks = 0
        relogged = False
        last_location = ""
        obs = self.driver.observe()

        for step_no in range(1, self.max_steps + 1):
            if self.should_stop():
                return LoopOutcome(final="blocked", reason="Dihentikan pengguna (Ctrl+C)", steps=step_no - 1,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="interrupted")

            if self.relogin and not (login or allow_logout or relogged) and obs.is_login_screen and last_location:
                relogged = True
                self.relogin(last_location)
                obs = self.driver.observe()
                notes.append("Sesi login kedaluwarsa; sistem sudah login ulang dan kembali ke halaman terakhir. Lanjutkan tujuan.")

            signals.extend(obs.signals)
            message = prompts.step_message(goal, obs, history[-HISTORY_WINDOW:], notes, self.vision)
            message.text = self.masker.mask(message.text) or ""
            notes = []
            try:
                action = self._decide(system, message, len(obs.elements))
            except ActionParseError as e:
                self._record(tc_id, step_no, obs, None, None, f"error: jawaban AI tidak valid ({e})")
                history.append(f"{step_no}. (jawaban AI tidak valid)")
                continue

            by_index = {e.index: e for e in obs.elements}
            element = by_index.get(action.element) if action.element is not None else None

            if action.action in ("done", "blocked"):
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot())
                self._record(tc_id, step_no, obs, action, None, "ok", shot)
                if action.action == "done":
                    return LoopOutcome(final="done", status=action.status, actual=self.masker.mask(action.actual or "") or "",
                                       severity=action.severity, steps=step_no, guard_blocks=guard_blocks, signals=signals)
                return LoopOutcome(final="blocked", reason=self.masker.mask(action.reason or "AI menyatakan blocked") or "",
                                   actual=self.masker.mask(action.actual or "") or "", steps=step_no,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="agent")

            target = element.selector if element is not None else (action.value or "")
            verdict = detector.record(obs.fingerprint, action.action, target)
            if verdict == "block":
                self._record(tc_id, step_no, obs, action, element, "error: langkah berulang tanpa kemajuan")
                return LoopOutcome(final="blocked", reason="Langkah yang sama diulang tanpa kemajuan", steps=step_no,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="loop")
            if verdict == "warn":
                notes.append("PERINGATAN: aksi ini sudah dicoba berulang kali di layar yang sama. Pilih aksi lain atau nyatakan blocked.")

            description = humanize(action.action, _element_dict(element), self.masker.mask(action.value))
            decision = self.guard.check(action, element, allow_logout=allow_logout, login=login)
            if not decision.allowed:
                guard_blocks += 1
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot(highlight=element))
                self._record(tc_id, step_no, obs, action, element, "skipped", shot, guard=f"blocked: {decision.reason}")
                notes.append(f"Aksi '{description}' diblok Safety Guard: {decision.reason}. Cari jalan lain atau nyatakan blocked.")
                history.append(f"{step_no}. {description} → DIBLOK")
                continue

            before = self.driver.screenshot(highlight=element) if action.action == "click" and element is not None else None
            result = self.driver.execute(action, element)
            if not result.ok and not result.fatal and element is not None:
                fresh = self.driver.observe()
                again = find_same(fresh, element)
                if again is not None:
                    element = again
                    result = self.driver.execute(action, again)
            if result.fatal:
                raise DriverCrashed(result.error or "Browser tertutup")

            after = before if before is not None else self.driver.screenshot(
                highlight=element if action.action in ("type", "select") else None)
            shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", after)
            outcome_text = "ok" if result.ok else f"error: {result.error}"
            self._record(tc_id, step_no, obs, action, element, outcome_text, shot)
            history.append(f"{step_no}. {description} → {'ok' if result.ok else 'gagal: ' + (self.masker.mask(result.error) or '')}")
            last_location = obs.location
            obs = self.driver.observe()

        return LoopOutcome(final="blocked", reason=f"Batas {self.max_steps} langkah tercapai", steps=self.max_steps,
                           guard_blocks=guard_blocks, signals=signals, error_kind="max_steps")

    def _decide(self, system: str, message: Message, element_count: int) -> Action:
        reply = self.llm.chat(system, [message])
        try:
            return parse_action(reply, element_count)
        except ActionParseError as e:
            retry = [message, Message(role="assistant", text=reply or ""), prompts.retry_message(str(e))]
            return parse_action(self.llm.chat(system, retry), element_count)

    def _record(self, tc_id: str, step_no: int, obs: Observation, action: Action | None, element: Element | None,
                result: str, screenshot: str | None = None, guard: str = "allowed") -> None:
        if action is None:
            value = None
        elif action.action == "done":
            value = action.status
        elif action.action == "blocked":
            value = action.reason
        else:
            value = action.value
        self.store.append_step(StepRecord(
            tc_id=tc_id,
            step_no=step_no,
            timestamp=now_iso(),
            location=self.masker.mask(obs.location) or "",
            fingerprint=obs.fingerprint,
            thought=self.masker.mask(action.thought) if action else "",
            action=action.action if action else "invalid",
            element=_element_dict(element),
            value=self.masker.mask(value),
            expect=action.expect if action else "",
            guard=guard,
            result=self.masker.mask(result) or "",
            signals=[s.model_copy(update={"message": self.masker.mask(s.message), "url": self.masker.mask(s.url)})
                     for s in obs.signals],
            screenshot=screenshot,
        ))
