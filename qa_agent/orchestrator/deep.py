from __future__ import annotations

import json
import re
from typing import Callable, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError, field_validator

from qa_agent.agent import prompts
from qa_agent.agent.control import RunControl
from qa_agent.agent.loop import AgentLoop, LoopOutcome
from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.drivers.base import Driver
from qa_agent.evidence import RunStore, module_abbr
from qa_agent.guard import LOGOUT_KEYWORDS
from qa_agent.llm.base import LLMClient, LLMError, Message
from qa_agent.models import AppMap, QaTestCase, ScreenInfo, TcType
from qa_agent.orchestrator.auth import AuthManager, LoginFailed


class PlanError(Exception):
    """Test case tidak bisa disusun."""


class _Interrupted(Exception):
    """Run dihentikan QA di tengah persiapan test case."""


class PlannedCase(BaseModel):
    title: str
    page: str = ""
    type: TcType = "positif"
    priority: Literal["High", "Medium", "Low"] = "Medium"
    precondition: str = ""
    test_data: str = ""
    steps: list[str]
    expected: str
    expected_source: Literal["PRD", "Inferensi AI"] = "Inferensi AI"
    start_url: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _type_lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_capitalized(cls, v):
        return v.strip().capitalize() if isinstance(v, str) else v

    @field_validator("precondition", "test_data", "page", "start_url", mode="before")
    @classmethod
    def _as_text(cls, v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_as_list(cls, v):
        if isinstance(v, str):
            return [line.strip() for line in v.splitlines() if line.strip()]
        return v

    @field_validator("expected_source", mode="before")
    @classmethod
    def _source(cls, v):
        return "PRD" if isinstance(v, str) and v.strip().upper() == "PRD" else "Inferensi AI"


def _resolve_start(planned: PlannedCase, screens: list[ScreenInfo]) -> str:
    urls = [s.url for s in screens]
    if planned.start_url in urls:
        return planned.start_url
    if planned.start_url:
        wanted = urlsplit(planned.start_url).path or planned.start_url
        for u in urls:
            if urlsplit(u).path == wanted:
                return u
    page = planned.page.strip().lower()
    for s in screens:
        if page and s.page_name.strip().lower() == page:
            return s.url
    return screens[0].url


class DeepPlanner:
    def __init__(self, llm: LLMClient, *, data_prefix: str, max_tcs: int = 15, skills: str = "") -> None:
        self.skills = skills  # bagian '## Skill QA' (tahap Menyusun test case & Menulis laporan)
        self.llm = llm
        self.data_prefix = data_prefix
        self.max_tcs = max_tcs

    def plan(self, app_map: AppMap, module: str, prd_text: str | None = None) -> list[QaTestCase]:
        canonical = app_map.find_module(module)
        if canonical is None:
            available = ", ".join(app_map.modules()) or "(kosong)"
            raise PlanError(f"Modul '{module.strip()}' tidak ditemukan di hasil explore. Modul yang tersedia: {available}")
        screens = app_map.screens_for(canonical)
        system = prompts.plan_system(canonical, self.max_tcs, self.data_prefix, bool(prd_text), skills=self.skills)
        first = prompts.plan_message(screens, prd_text)
        messages = [first]
        error = ""
        for _ in range(2):
            reply = self.llm.chat(system, messages)
            try:
                items = extract_json(reply, "test_cases").get("test_cases")
                if not isinstance(items, list):
                    raise ActionParseError("field 'test_cases' harus berupa list")
                cases = self._to_cases(items, canonical, screens, has_prd=bool(prd_text))
                if cases:
                    return cases
                error = "tidak ada test case yang valid"
            except ActionParseError as e:
                error = str(e)
            messages = [first, Message(role="assistant", text=reply or ""),
                        Message(role="user", text=f"Jawaban tidak valid: {error}. Ulangi sesuai format.")]
        raise PlanError(f"AI gagal menyusun test case: {error}")

    def _to_cases(self, items: list, module: str, screens: list[ScreenInfo], *, has_prd: bool) -> list[QaTestCase]:
        abbr = module_abbr(module)
        cases: list[QaTestCase] = []
        for item in items:
            if len(cases) >= self.max_tcs:
                break
            if not isinstance(item, dict):
                continue
            try:
                planned = PlannedCase.model_validate(item)
            except ValidationError:
                continue
            cases.append(QaTestCase(
                id=f"TC-{abbr}-{len(cases) + 1:03d}", module=module, page=planned.page, title=planned.title,
                type=planned.type, priority=planned.priority, precondition=planned.precondition,
                test_data=valid_login_test_data(planned.title, planned.test_data, planned.steps),
                steps=planned.steps, expected=planned.expected,
                expected_source=planned.expected_source if has_prd else "Inferensi AI",
                start_url=_resolve_start(planned, screens),
            ))
        return cases


_PASSWORD_IN_DATA = re.compile(r"password|kata sandi", re.IGNORECASE)
_EMPTY = re.compile(r"kosong|empty|blank", re.IGNORECASE)


def valid_login_test_data(title: str, test_data: str, steps: list[str]) -> str:
    """Test case login sukses memakai akun test tersimpan, bukan akun karangan AI.
    Data karangan hanya dipertahankan untuk skenario gagal (kredensial salah / field kosong)."""
    text = " ".join([title, test_data, *steps])
    if (not test_data or not _PASSWORD_IN_DATA.search(test_data) or _NEGATIVE_CREDENTIAL.search(text)
            or _EMPTY.search(text)):
        return test_data
    return "Akun test tersimpan: username {{username}}, password {{password}}"


def judge(outcome: LoopOutcome, tc: QaTestCase) -> tuple[str, str | None]:
    """Aturan status (spec §6.4). Request yang diblok mode production → Skipped (hasilnya tidak bisa dinilai);
    selain itu HTTP 5xx / error JavaScript selalu menang → Fail. Keputusan QA (lewati / akhiri manual) paling utama."""
    if outcome.error_kind == "skipped_by_qa":
        return "Blocked", None
    if outcome.error_kind == "ended_by_qa":
        return ("Pass", None) if outcome.status == "pass" else ("Fail", outcome.severity)
    if any(s.kind == "blocked_request" for s in outcome.signals):
        return "Skipped", None
    server_error = any(s.kind == "page_error" or (s.kind == "http_error" and (s.status or 0) >= 500) for s in outcome.signals)
    if server_error:
        return "Fail", outcome.severity or "Major"
    if outcome.final == "blocked":
        return ("Skipped" if outcome.guard_blocks > 0 else "Blocked"), None
    if outcome.status == "fail":
        return ("Fail" if tc.expected_source == "PRD" else "Perlu Review"), outcome.severity or "Minor"
    return "Pass", None


_NEGATIVE_CREDENTIAL = re.compile(
    r"(password|kata sandi|username|user ?name|kredensial|akun)\s+(salah|tidak valid|invalid|tidak terdaftar|keliru)"
    r"|wrong password|invalid credential|tidak terdaftar", re.IGNORECASE)


_CREDENTIAL_WORDS = re.compile(r"password|kata sandi|username|user ?name|kredensial|sign ?in|log ?in|masuk", re.IGNORECASE)


def goal_for(tc: QaTestCase, start_problem: str = "") -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(tc.steps, 1)) or "-"
    if start_problem:
        start_problem = (
            f"\nCATATAN SISTEM: layar awal test case ini ({tc.page or tc.start_url}) tidak bisa dibuka otomatis: "
            f"{start_problem}\nMulai dari layar yang tampil sekarang dan cari cara mencapai layar awal itu; utamakan "
            "arahan QA bila ada. Jika layar itu memang tidak bisa dimunculkan saat ini, nyatakan blocked dengan alasan "
            "yang jelas.\n")
    text = " ".join([tc.title, tc.test_data, *tc.steps])
    negative = _NEGATIVE_CREDENTIAL.search(text)
    reminder = ("\nPENTING: ini skenario kredensial salah. {{password}} dan {{username}} adalah kredensial yang BENAR, "
                "jadi untuk nilai yang harus salah ketik teks literal (mis. Salah#12345 / tidakterdaftar_qa). "
                "Bagian yang memang valid (mis. username valid) tetap pakai {{username}}.\n") if negative else ""
    if _CREDENTIAL_WORDS.search(text):
        reminder += ("\nKredensial VALID selalu dari akun test yang tersimpan: ketik {{username}} dan {{password}}. "
                     "Abaikan contoh username/password di test data bila itu untuk akun yang valid (contoh itu karangan, "
                     "bukan akun sungguhan).\n")
    return (
        f"Jalankan test case {tc.id}: {tc.title}\n{reminder}{start_problem}"
        f"Tipe: {tc.type}\n"
        f"Pre-condition: {tc.precondition or '-'}\n"
        f"Test data: {tc.test_data or '-'}\n"
        f"Langkah:\n{steps}\n"
        f"Expected result: {tc.expected}\n\n"
        "Ikuti langkah di atas di aplikasi. Setelah langkah terakhir, bandingkan kondisi layar dengan expected result, "
        "lalu nyatakan done (pass/fail) dengan actual yang menjelaskan apa yang terjadi."
    )


def is_logout_case(tc: QaTestCase) -> bool:
    text = " ".join([tc.title, *tc.steps]).lower()
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text) for k in LOGOUT_KEYWORDS)


_LOGGED_IN = re.compile(r"(sudah|telah|dalam keadaan|berhasil)\s+(login|log in|masuk|sign[ -]?in)|logged[ -]?in"
                        r"|authenticated|sesi (login )?aktif", re.IGNORECASE)


def requires_login(tc: QaTestCase) -> bool:
    """Pre-condition test case menyebut pengguna sudah login."""
    return bool(_LOGGED_IN.search(tc.precondition or ""))


LOGOUT_GOAL = (
    "Keluar (logout) dari akun di aplikasi ini sampai halaman login tampil. Cari tombol/menu Logout, Keluar, Sign out, "
    "atau Log out: periksa menu samping (ikon garis tiga), menu profil/akun, tab Akun/Profil/Pengaturan, dan menu titik "
    "tiga; gulir ke bawah bila perlu. Konfirmasi dialog logout bila muncul. Nyatakan done status pass setelah halaman "
    "login tampil, atau status fail bila tombol logout benar-benar tidak ada."
)


class DeepRunner:
    def __init__(self, *, driver: Driver, loop: AgentLoop, auth: AuthManager | None, store: RunStore,
                 should_stop: Callable[[], bool] = lambda: False,
                 on_event: Callable[[dict], None] = lambda e: None, control: RunControl | None = None) -> None:
        self.driver = driver
        self.loop = loop
        self.auth = auth
        self.store = store
        self.should_stop = should_stop
        self.on_event = on_event
        self.control = control
        self._logout_steps: list[dict] | None = None  # jalur logout yang berhasil, diputar ulang tanpa AI
        self._logouts = 0
        self._unreachable: dict[str, tuple[str, str]] = {}  # layar awal → (TC pertama yang gagal, alasan)

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass

    def execute(self, cases: list[QaTestCase], *, needs_auth: bool,
                public_starts: set[str] | frozenset[str] = frozenset()) -> list[QaTestCase]:
        """`public_starts`: layar sebelum login (mis. Sign In). Test case yang dimulai di sana selalu tanpa sesi login."""
        self._public_starts = set(public_starts)
        relogin = self.auth.relogin if (needs_auth and self.auth is not None) else None
        self.loop.relogin = relogin
        for tc in cases:
            # Test case di layar publik (Sign In) menguji form login: jangan login ulang otomatis saat form login tampil
            self.loop.relogin = None if (tc.start_url or "/") in self._public_starts else relogin
            if tc.status_ai is not None:
                continue  # sudah selesai (resume)
            if self.should_stop():
                break
            # Jeda QA juga berlaku di antara test case (persiapan layar tidak berjalan di balik layar)
            if self.control is not None and self.control.wait_until_running() == "stop":
                break
            self.store.drop_steps(tc.id)
            self._emit({"type": "tc.started", "tc_id": tc.id, "title": tc.title})
            try:
                self.loop.last_signals = []
                start = tc.start_url or "/"
                start_problem = ""
                try:
                    self._prepare(tc, needs_auth)
                except RuntimeError as e:
                    # Layar awal tidak bisa dibuka otomatis: biarkan agent mencoba dari layar saat ini (arahan QA
                    # ikut dibaca). Layar yang sama sudah terbukti tidak bisa dicapai → langsung Blocked, kecuali
                    # QA sedang memberi arahan.
                    earlier = self._unreachable.get(start)
                    hints_waiting = self.control is not None and self.control.has_hints()
                    if earlier and not hints_waiting:
                        tc.status_ai = "Blocked"
                        tc.actual = f"Layar awal sama dengan {earlier[0]} yang tidak bisa dicapai: {earlier[1]}"
                        tc.ai_note = "Beri arahan agent (Arahkan agent) atau jalankan ulang saat layar ini bisa dimunculkan"
                        self.store.write_testcases(cases)
                        self._emit({"type": "tc.finished", "tc_id": tc.id, "status": tc.status_ai})
                        continue
                    start_problem = str(e)
                # Error yang muncul saat login/logout otomatis (mis. popup setelah login) tidak boleh hilang
                prep_errors = [s.message for s in getattr(self.loop, "last_signals", [])
                               if s.kind in ("ui_error", "page_error", "console_error")
                               or (s.kind == "http_error" and (s.status or 0) >= 500)]
                outcome = self.loop.run(tc.id, goal_for(tc, start_problem), allow_logout=is_logout_case(tc))
                if outcome.error_kind == "interrupted":
                    self._emit({"type": "tc.finished", "tc_id": tc.id, "status": None})
                    break  # biarkan status kosong supaya dijalankan ulang saat resume
                if start_problem and outcome.final == "blocked":
                    self._unreachable[start] = (tc.id, outcome.reason or start_problem)
                elif start_problem:
                    self._unreachable.pop(start, None)
                tc.status_ai, tc.severity = judge(outcome, tc)
                tc.actual = outcome.actual or outcome.reason
                tc.ai_note = outcome.reason if outcome.final == "blocked" else ""
                if prep_errors:
                    note = "Saat login/logout otomatis sebelum test case ini muncul: " + "; ".join(dict.fromkeys(prep_errors))
                    tc.ai_note = f"{tc.ai_note} {note}".strip()
                    if tc.status_ai == "Pass":
                        tc.status_ai = "Perlu Review"
            except _Interrupted:
                self._emit({"type": "tc.finished", "tc_id": tc.id, "status": None})
                break
            except (LLMError, LoginFailed):
                self.store.write_testcases(cases)
                self._emit({"type": "tc.finished", "tc_id": tc.id, "status": None})
                raise
            except Exception as e:  # satu test case gagal tidak menghentikan run
                tc.status_ai = "Blocked"
                tc.actual = f"Error sistem: {type(e).__name__}: {e}"
                self._recover()
            self.store.write_testcases(cases)
            self._emit({"type": "tc.finished", "tc_id": tc.id, "status": tc.status_ai})
        return cases

    def _prepare(self, tc: QaTestCase, needs_auth: bool) -> None:
        start = tc.start_url or "/"
        public_start = start in getattr(self, "_public_starts", set())
        logged_in = requires_login(tc) or is_logout_case(tc) or (needs_auth and not public_start)
        if logged_in and self.auth is not None:
            self.auth.start_authenticated(start)
        else:
            self.driver.new_session(None)
            if getattr(self.driver, "keeps_login", False):
                self._ensure_logged_out()
            self.driver.goto(start)

    def _ensure_logged_out(self) -> None:
        """Android: sesi login tetap tersimpan saat aplikasi dibuka ulang, jadi logout dulu (setara sesi baru di web)."""
        if self.driver.observe().is_login_screen:
            return
        replay = getattr(self.driver, "replay_steps", None)
        if self._logout_steps and replay is not None:
            replay(self._logout_steps)
            if self.driver.observe().is_login_screen:
                return
            self.driver.new_session(None)
        self._logouts += 1
        record = getattr(self.driver, "start_recording", None)
        if record is not None:
            record()
        outcome = self.loop.run(f"LOGOUT-{self._logouts}", LOGOUT_GOAL, allow_logout=True)
        stop_record = getattr(self.driver, "stop_recording", None)
        steps = stop_record() if stop_record is not None else None
        if outcome.error_kind == "interrupted":
            raise _Interrupted()
        if not self.driver.observe().is_login_screen:
            reason = outcome.actual or outcome.reason or "halaman login tidak tampil"
            raise RuntimeError(f"Tidak bisa logout otomatis sebelum test case ini: {reason}. "
                               "Arahkan agent ke tombol logout, atau logout manual lewat Ambil alih")
        if steps:
            self._logout_steps = steps

    def _recover(self) -> None:
        try:
            self.driver.new_session(None)
        except Exception:
            try:
                self.driver.stop()
            except Exception:
                pass
            self.driver.start()
