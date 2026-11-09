from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]
ActionType = Literal["click", "type", "select", "scroll", "back", "navigate", "wait", "done", "blocked"]
Status = Literal["Pass", "Fail", "Perlu Review", "Blocked", "Skipped"]
Severity = Literal["Critical", "Major", "Minor"]
TcType = Literal["positif", "negatif", "validasi", "boundary", "navigasi"]

_LOGIN_PATH = re.compile(r"login|signin|sign-in|auth|masuk", re.IGNORECASE)
_LOGIN_BUTTON = re.compile(r"(?<!\w)(login|log in|masuk|sign in|signin)(?!\w)", re.IGNORECASE)

STATUSES: tuple[str, ...] = ("Pass", "Fail", "Perlu Review", "Blocked", "Skipped")
TC_TYPES: tuple[str, ...] = ("positif", "negatif", "validasi", "boundary", "navigasi")


class Element(BaseModel):
    index: int
    role: str
    name: str = ""
    input_type: str | None = None
    value: str | None = None
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    selector: str = ""
    href: str | None = None
    context: str = ""
    frame: int = 0


class Signal(BaseModel):
    kind: Literal["console_error", "page_error", "http_error", "ui_error", "blocked_request"]
    message: str
    status: int | None = None
    url: str | None = None
    method: str | None = None


class Observation(BaseModel):
    location: str
    title: str = ""
    elements: list[Element] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    screenshot_annotated: bytes = b""
    fingerprint: str = ""

    @property
    def is_login_screen(self) -> bool:
        """Tepat satu field password DAN (path bernuansa login ATAU tombol login/masuk).

        Form biasa yang punya field password (mis. "Tambah Pengguna", pengaturan SMTP) bukan halaman login.
        """
        if sum(1 for e in self.elements if e.input_type == "password") != 1:
            return False
        if _LOGIN_PATH.search(urlsplit(self.location).path):
            return True
        return any(e.role == "button" and _LOGIN_BUTTON.search(e.name) for e in self.elements)


class Action(BaseModel):
    thought: str = ""
    action: ActionType
    element: int | None = None
    value: str | None = None
    expect: str = ""
    risk: Risk = "low"
    status: Literal["pass", "fail"] | None = None
    actual: str | None = None
    reason: str | None = None
    severity: Severity | None = None


class ActionResult(BaseModel):
    ok: bool
    error: str | None = None
    fatal: bool = False


class GuardDecision(BaseModel):
    allowed: bool
    risk: Risk = "low"
    reason: str = ""


class QaTestCase(BaseModel):
    id: str
    module: str
    page: str = ""
    title: str
    type: TcType = "positif"
    priority: Literal["High", "Medium", "Low"] = "Medium"
    precondition: str = ""
    test_data: str = ""
    steps: list[str] = Field(default_factory=list)
    expected: str
    expected_source: Literal["PRD", "Inferensi AI"] = "Inferensi AI"
    start_url: str = ""
    status_ai: Status | None = None
    actual: str = ""
    ai_note: str = ""
    severity: Severity | None = None
    status_final: Status | None = None
    reviewer_note: str = ""

    @property
    def effective_status(self) -> str | None:
        return self.status_final or self.status_ai


class StepRecord(BaseModel):
    tc_id: str
    step_no: int
    timestamp: str
    location: str = ""
    fingerprint: str = ""
    thought: str = ""
    action: str
    element: dict[str, str] | None = None
    value: str | None = None
    expect: str = ""
    guard: str = "allowed"
    result: str = "ok"
    signals: list[Signal] = Field(default_factory=list)
    screenshot: str | None = None
    actor: Literal["ai", "manual"] = "ai"


class ScreenInfo(BaseModel):
    fingerprint: str
    url: str
    module: str
    page_name: str
    purpose: str = ""
    forms: list[dict] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    screenshot: str | None = None
    depth: int = 0
    parent: str | None = None
    public: bool = False
    nav_path: list[dict] = Field(default_factory=list)  # Android: urutan tap dari awal aplikasi ke layar ini


class AppMap(BaseModel):
    target: str
    screens: list[ScreenInfo] = Field(default_factory=list)

    def modules(self) -> list[str]:
        seen: list[str] = []
        for s in self.screens:
            if s.module not in seen:
                seen.append(s.module)
        return seen

    def find_module(self, name: str) -> str | None:
        wanted = " ".join(name.split()).lower()
        return next((m for m in self.modules() if m.lower() == wanted), None)

    def screens_for(self, module: str) -> list[ScreenInfo]:
        canonical = self.find_module(module)
        return [s for s in self.screens if s.module == canonical] if canonical else []


class RunMeta(BaseModel):
    mode: Literal["explore", "deep"]
    target: str
    environment: Literal["dev", "production"]
    model: str
    started_at: str
    finished_at: str | None = None
    status: Literal["running", "paused", "completed", "interrupted"] = "running"
    module: str | None = None
    source_run: str | None = None
    note: str = ""
