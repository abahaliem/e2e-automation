from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Literal

from qa_agent.agent import prompts
from qa_agent.agent.control import ControlDecision, RunControl
from qa_agent.agent.loop_detect import LoopDetector
from qa_agent.agent.parser import ActionParseError, parse_action
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import Masker, RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient, Message
from qa_agent.models import Action, Element, Observation, Signal, StepRecord
from qa_agent.report.humanize import humanize

HISTORY_WINDOW = 8
SKIPPED_BY_QA = "Dilewati oleh QA"
VERIFIED_BY_QA = "Diverifikasi manual oleh QA"


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
    # "", "max_steps", "loop", "interrupted", "agent", "skipped_by_qa", "ended_by_qa"
    error_kind: str = ""


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


def element_at(obs: Observation, event: dict, size: dict | None) -> Element | None:
    """Elemen terkecil di observasi yang memuat titik klik QA (koordinat 0..1 → piksel)."""
    if not size or not size.get("width") or not size.get("height"):
        return None
    try:
        px = float(event.get("x", 0)) * size["width"]
        py = float(event.get("y", 0)) * size["height"]
    except (TypeError, ValueError):
        return None
    hits = [e for e in obs.elements
            if e.bbox[2] > 0 and e.bbox[3] > 0
            and e.bbox[0] <= px <= e.bbox[0] + e.bbox[2] and e.bbox[1] <= py <= e.bbox[1] + e.bbox[3]]
    return min(hits, key=lambda e: e.bbox[2] * e.bbox[3]) if hits else None


def describe_manual(event: dict, masker: Masker, target: Element | None = None) -> str:
    """Deskripsi singkat input manual QA; teks yang diketik selalu disamarkan."""
    kind = event.get("kind")
    if kind == "click":
        if target is not None and (target.name or "").strip():
            name = " ".join(target.name.split())[:60]
            return f"Klik '{masker.mask(name)}'"
        return f"Klik di area ({float(event.get('x', 0)):.2f}, {float(event.get('y', 0)):.2f}) tanpa nama elemen"
    if kind == "type":
        text = str(event.get("text", ""))
        return f"Ketik {len(text)} karakter" if text else "Ketik (kosong)"
    if kind == "key":
        return f"Tekan tombol {event.get('key', '')}"
    if kind == "scroll":
        return "Gulir ke bawah" if int(event.get("dy", 0)) >= 0 else "Gulir ke atas"
    return masker.mask(str(kind)) or "Input manual"


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
        control: RunControl | None = None,
        on_event: Callable[[dict], None] = lambda e: None,
        skills: str = "",
    ) -> None:
        self.skills = skills  # bagian '## Skill QA' (tahap Menjalankan test & Menilai hasil)
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
        self.control = control
        self.on_event = on_event
        self.last_signals: list[Signal] = []
        self._trace: dict = {"steps": [], "start_names": [], "end_names": [], "end_location": ""}
        self.last_trace: dict = self._trace

    # ------------------------------------------------------------------
    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:  # event tidak boleh menggagalkan test case
            pass

    def run(self, tc_id: str, goal: str, *, allow_logout: bool = False, login: bool = False) -> LoopOutcome:
        try:
            result = self._run(tc_id, goal, allow_logout=allow_logout, login=login)
            self.last_signals = list(result.signals)  # dibaca DeepRunner untuk login/logout otomatis
            if result.final == "done":  # test case diakhiri QA: layar akhir = layar saat itu
                trace = self._trace
                if not trace["end_names"]:
                    try:
                        end = self.driver.observe()
                        trace["end_names"], trace["end_location"] = [e.name for e in end.elements], end.location
                    except Exception:
                        pass
            self.last_trace = self._trace
            return result
        finally:
            if self.control is not None:  # perintah khusus test case ini tidak terbawa ke test case berikutnya
                self.control.reset_case()

    def _run(self, tc_id: str, goal: str, *, allow_logout: bool, login: bool) -> LoopOutcome:
        system = prompts.execute_system(self.platform, self.data_prefix, skills=self.skills)
        history: list[str] = []
        notes: list[str] = []
        hints: list[str] = []
        manual_log: list[str] = []
        signals: list[Signal] = []
        detector = LoopDetector()
        guard_blocks = 0
        relogged = False
        last_location = ""
        step_no = 0   # nomor rekaman langkah (AI + manual)
        ai_steps = 0  # anggaran langkah AI
        obs = self.driver.observe()
        # Trace langkah yang benar-benar dijalankan → skrip regresi tanpa AI bila test case Pass
        self._trace = {"steps": [], "start_names": [e.name for e in obs.elements], "end_names": [],
                       "end_location": obs.location}

        def outcome(**kw) -> LoopOutcome:
            return LoopOutcome(steps=step_no, guard_blocks=guard_blocks, signals=signals, **kw)

        def from_control(d: ControlDecision) -> LoopOutcome | None:
            if d.kind == "stop":
                return outcome(final="blocked", reason="Dihentikan oleh QA", error_kind="interrupted")
            if d.kind == "skip":
                return outcome(final="blocked", reason=SKIPPED_BY_QA, error_kind="skipped_by_qa")
            if d.kind == "end_case":
                actual = VERIFIED_BY_QA + (f": {self.masker.mask(d.note)}" if d.note else "")
                return outcome(final="done", status=d.end_status, actual=actual, error_kind="ended_by_qa")
            return None

        while ai_steps < self.max_steps:
            if self.should_stop():
                return outcome(final="blocked", reason="Dihentikan pengguna (Ctrl+C)", error_kind="interrupted")

            # ---- titik kontrol (a): sebelum AI memutuskan ----
            if self.control is not None:
                d = self.control.wait_before_decide()
                done = from_control(d)
                if done is not None:
                    return done
                if d.kind == "manual_input":
                    step_no += 1
                    manual_log.append(self._manual(tc_id, step_no, obs, d.input or {}))
                    obs = self.driver.observe()
                    continue
                for text in d.hints:
                    step_no += 1
                    hints.append(text)
                    self._record_hint(tc_id, step_no, obs, text)
                if manual_log:
                    notes.append("QA melakukan langkah manual: " + "; ".join(manual_log)
                                 + ". Lanjutkan tujuan dari kondisi layar saat ini.")
                    history.append(f"(QA) {'; '.join(manual_log)}")
                    manual_log = []

            if self.relogin and not (login or allow_logout or relogged) and obs.is_login_screen and last_location:
                relogged = True
                self.relogin(last_location)
                obs = self.driver.observe()
                notes.append("Sesi login kedaluwarsa; sistem sudah login ulang dan kembali ke halaman terakhir. Lanjutkan tujuan.")

            for s in obs.signals:
                self._emit({"type": "signal", "tc_id": tc_id, "signal": s.model_dump()})
            signals.extend(obs.signals)
            ai_steps += 1
            step_no += 1
            message = prompts.step_message(goal, obs, history[-HISTORY_WINDOW:], notes, self.vision, hints)
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
            description = humanize(action.action, _element_dict(element),
                                   self.masker.mask(action.status if action.action == "done" else
                                                    action.reason if action.action == "blocked" else action.value))
            if self.control is not None:
                self.control.expect_confirm()
            self._emit({
                "type": "step.planned", "tc_id": tc_id, "step_no": step_no, "action": action.action,
                "element": None if element is None else {"role": element.role, "name": element.name,
                                                         "bbox": list(element.bbox)},
                "thought": self.masker.mask(action.thought) or "", "risk": action.risk,
                "description": description, "viewport": self._viewport(),
            })

            # ---- titik kontrol (b): setelah keputusan, sebelum eksekusi ----
            if self.control is not None:
                d = self.control.wait_before_execute()
                done = from_control(d)
                if done is not None:
                    return done
                if d.kind == "think_again":
                    ai_steps -= 1
                    step_no -= 1
                    notes.append(f"Pikir ulang: QA membatalkan rencana '{description}'. Pilih langkah lain yang lebih tepat.")
                    hints.extend(d.hints)
                    continue
                if d.kind == "manual_input":
                    # QA mengambil alih sebelum rencana dijalankan: rencana dibuang.
                    ai_steps -= 1
                    manual_log.append(self._manual(tc_id, step_no, obs, d.input or {}))
                    obs = self.driver.observe()
                    continue

            if action.action in ("done", "blocked"):
                self._trace["end_names"] = [e.name for e in obs.elements]
                self._trace["end_location"] = obs.location
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot())
                self._record(tc_id, step_no, obs, action, None, "ok", shot)
                self._emit_done(tc_id, step_no, "ok", shot, description)
                if action.action == "done":
                    return outcome(final="done", status=action.status, actual=self.masker.mask(action.actual or "") or "",
                                   severity=action.severity)
                return outcome(final="blocked", reason=self.masker.mask(action.reason or "AI menyatakan blocked") or "",
                               actual=self.masker.mask(action.actual or "") or "", error_kind="agent")

            target = element.selector if element is not None else (action.value or "")
            verdict = detector.record(obs.fingerprint, action.action, target)
            if verdict == "block":
                self._record(tc_id, step_no, obs, action, element, "error: langkah berulang tanpa kemajuan")
                return outcome(final="blocked", reason="Langkah yang sama diulang tanpa kemajuan", error_kind="loop")
            if verdict == "warn":
                notes.append("PERINGATAN: aksi ini sudah dicoba berulang kali di layar yang sama. Pilih aksi lain atau nyatakan blocked.")

            decision = self.guard.check(action, element, allow_logout=allow_logout, login=login)
            if not decision.allowed:
                guard_blocks += 1
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot(highlight=element))
                self._record(tc_id, step_no, obs, action, element, "skipped", shot, guard=f"blocked: {decision.reason}")
                self._emit_done(tc_id, step_no, "skipped", shot, description)
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
            if result.ok:
                self._trace["steps"].append({"action": action.action, "element": _element_dict(element),
                                             "value": action.value})

            after = before if before is not None else self.driver.screenshot(
                highlight=element if action.action in ("type", "select") else None)
            shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", after)
            outcome_text = "ok" if result.ok else f"error: {result.error}"
            self._record(tc_id, step_no, obs, action, element, outcome_text, shot)
            self._emit_done(tc_id, step_no, self.masker.mask(outcome_text) or "", shot, description)
            history.append(f"{step_no}. {description} → {'ok' if result.ok else 'gagal: ' + (self.masker.mask(result.error) or '')}")
            last_location = obs.location
            obs = self.driver.observe()

        return outcome(final="blocked", reason=f"Batas {self.max_steps} langkah tercapai", error_kind="max_steps")

    # ------------------------------------------------------------------
    def _viewport(self) -> dict | None:
        size = getattr(self.driver, "viewport_size", None)
        if callable(size):
            try:
                size = size()
            except Exception:
                size = None
        return dict(size) if isinstance(size, dict) else None

    def _emit_done(self, tc_id: str, step_no: int, result: str, screenshot: str | None, description: str,
                   actor: str = "ai") -> None:
        self._emit({"type": "step.done", "tc_id": tc_id, "step_no": step_no, "result": result,
                    "screenshot": screenshot, "description": description, "actor": actor})

    def _manual(self, tc_id: str, step_no: int, obs: Observation, event: dict) -> str:
        """Jalankan satu input manual QA (tanpa Guard kata kunci; filter jaringan tetap aktif)."""
        target = None
        if event.get("kind") == "click":
            size_fn = getattr(self.driver, "viewport_size", None)
            try:
                target = element_at(obs, event, size_fn() if size_fn else None)
            except Exception:  # noqa: BLE001 - nama elemen hanya untuk keterangan
                target = None
        description = describe_manual(event, self.masker, target)
        manual = getattr(self.driver, "manual_input", None)
        if manual is None:
            result_text = "error: driver tidak mendukung input manual"
        else:
            result = manual(event)
            if result.fatal:
                raise DriverCrashed(result.error or "Browser tertutup")
            result_text = "ok" if result.ok else f"error: {result.error}"
            if result.ok and event.get("kind") in ("click", "key"):
                # QA perlu tahu apakah kliknya berpengaruh: bandingkan layar sebelum & sesudah
                try:
                    after = self.driver.observe()
                    changed = after.fingerprint != obs.fingerprint or after.location != obs.location
                    description += " → layar berubah" if changed else " → tidak ada perubahan di layar"
                except Exception:  # noqa: BLE001
                    pass
            trace = getattr(self, "_trace", None)
            if result.ok and trace is not None:
                trace["steps"].append({"manual": dict(event)})
        shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot())
        self.store.append_step(StepRecord(
            tc_id=tc_id, step_no=step_no, timestamp=now_iso(), location=self.masker.mask(obs.location) or "",
            fingerprint=obs.fingerprint, action="manual", value=description,
            result=self.masker.mask(result_text) or "", screenshot=shot, actor="manual",
        ))
        self._emit_done(tc_id, step_no, self.masker.mask(result_text) or "", shot,
                        humanize("manual", None, description), actor="manual")
        return description

    def _record_hint(self, tc_id: str, step_no: int, obs: Observation, text: str) -> None:
        masked = self.masker.mask(text)
        self.store.append_step(StepRecord(
            tc_id=tc_id, step_no=step_no, timestamp=now_iso(), location=self.masker.mask(obs.location) or "",
            fingerprint=obs.fingerprint, action="hint", value=masked, actor="manual",
        ))
        self._emit_done(tc_id, step_no, "ok", None, humanize("hint", None, masked), actor="manual")

    def _chat(self, system: str, messages: list[Message]) -> str:
        """Panggil AI di thread lain sambil worker terus memproses frame layar live (idle), supaya live tidak beku."""
        idle = self.control.idle if self.control is not None else None
        if idle is None:
            return self.llm.chat(system, messages)
        box: dict = {}

        def call() -> None:
            try:
                box["reply"] = self.llm.chat(system, messages)
            except BaseException as e:  # diteruskan ke worker
                box["error"] = e

        thread = threading.Thread(target=call, name="llm-call", daemon=True)
        thread.start()
        while thread.is_alive():
            try:
                idle()
            except Exception:
                pass
            thread.join(0.05)
        if "error" in box:
            raise box["error"]
        return box["reply"]

    def _decide(self, system: str, message: Message, element_count: int) -> Action:
        reply = self._chat(system, [message])
        try:
            return parse_action(reply, element_count)
        except ActionParseError as e:
            retry = [message, Message(role="assistant", text=reply or ""), prompts.retry_message(str(e))]
            return parse_action(self._chat(system, retry), element_count)

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
