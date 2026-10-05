from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError, field_validator

from qa_agent.agent import prompts
from qa_agent.agent.loop import LoopOutcome
from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.evidence import module_abbr
from qa_agent.guard import LOGOUT_KEYWORDS
from qa_agent.llm.base import LLMClient, Message
from qa_agent.models import AppMap, QaTestCase, ScreenInfo, TcType


class PlanError(Exception):
    """Test case tidak bisa disusun."""


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
    def __init__(self, llm: LLMClient, *, data_prefix: str, max_tcs: int = 15) -> None:
        self.llm = llm
        self.data_prefix = data_prefix
        self.max_tcs = max_tcs

    def plan(self, app_map: AppMap, module: str, prd_text: str | None = None) -> list[QaTestCase]:
        canonical = app_map.find_module(module)
        if canonical is None:
            available = ", ".join(app_map.modules()) or "(kosong)"
            raise PlanError(f"Modul '{module.strip()}' tidak ditemukan di hasil explore. Modul yang tersedia: {available}")
        screens = app_map.screens_for(canonical)
        system = prompts.plan_system(canonical, self.max_tcs, self.data_prefix, bool(prd_text))
        first = prompts.plan_message(screens, prd_text)
        messages = [first]
        error = ""
        for _ in range(2):
            reply = self.llm.chat(system, messages)
            try:
                items = extract_json(reply).get("test_cases")
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
                test_data=planned.test_data, steps=planned.steps, expected=planned.expected,
                expected_source=planned.expected_source if has_prd else "Inferensi AI",
                start_url=_resolve_start(planned, screens),
            ))
        return cases


def judge(outcome: LoopOutcome, tc: QaTestCase) -> tuple[str, str | None]:
    """Aturan status (spec §6.4). HTTP 5xx / error JavaScript selalu menang → Fail."""
    server_error = any(s.kind == "page_error" or (s.kind == "http_error" and (s.status or 0) >= 500) for s in outcome.signals)
    if server_error:
        return "Fail", outcome.severity or "Major"
    if outcome.final == "blocked":
        return ("Skipped" if outcome.guard_blocks > 0 else "Blocked"), None
    if outcome.status == "fail":
        return ("Fail" if tc.expected_source == "PRD" else "Perlu Review"), outcome.severity or "Minor"
    return "Pass", None


def goal_for(tc: QaTestCase) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(tc.steps, 1)) or "-"
    return (
        f"Jalankan test case {tc.id}: {tc.title}\n"
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
