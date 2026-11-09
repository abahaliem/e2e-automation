from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from qa_agent.server.api import deps
from qa_agent.server.runs import REVIEW_NOTE, RunRequest
from qa_agent.server.store import RunRow

router = APIRouter(prefix="/api", tags=["runs"])


class RunIn(BaseModel):
    app_id: int
    mode: Literal["explore", "deep"]
    module: str | None = None
    prd_text: str | None = Field(default=None, max_length=200_000)
    profile_id: int | None = None
    account_id: int | None = None
    environment: Literal["dev", "production"] = "dev"
    confirm_each_step: bool = False
    device_serial: str | None = Field(default=None, max_length=120)
    apk_file: str | None = Field(default=None, max_length=255)
    apk_grant: bool = True
    apk_uninstall: bool = False
    review_first: bool = False
    reuse_cases_from: int | None = None


class PlanCaseIn(BaseModel):
    id: str | None = None
    title: str = Field(max_length=300)
    page: str = Field(default="", max_length=200)
    type: Literal["positif", "negatif", "validasi", "boundary", "navigasi"] = "positif"
    priority: Literal["High", "Medium", "Low"] = "Medium"
    precondition: str = Field(default="", max_length=2000)
    test_data: str = Field(default="", max_length=2000)
    steps: list[str] = Field(default_factory=list, max_length=50)
    expected: str = Field(max_length=2000)
    expected_source: Literal["PRD", "Inferensi AI"] = "Inferensi AI"
    start_url: str = Field(max_length=500)


class PlanIn(BaseModel):
    cases: list[PlanCaseIn] = Field(max_length=100)


class ControlIn(BaseModel):
    command: Literal["pause", "resume", "takeover", "release", "hint", "think_again", "skip", "stop", "end_case",
                     "confirm_step", "input"]
    text: str | None = Field(default=None, max_length=2000)
    status: Literal["pass", "fail"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    event: dict | None = None


def run_out(request: Request, row: RunRow) -> dict:
    store = deps.store(request)
    app = store.get_app(row.app_id)
    manager = deps.manager(request)
    data = row.model_dump(exclude={"options"})
    data["app_name"] = app.name if app else ""
    data["platform"] = app.platform if app else "web"
    data["url"] = app.url if app else ""
    data["confirm_each_step"] = bool(row.options.get("confirm_each_step"))
    data["device_serial"] = row.options.get("device_serial")
    data["created_by"] = row.options.get("created_by")
    data["review_first"] = bool(row.options.get("review_first"))
    data["reuse_cases_from"] = row.options.get("reuse_cases_from")
    data["awaiting_review"] = row.status == "paused" and row.note == REVIEW_NOTE
    data["active"] = manager.is_active(row.id)
    data["control_state"] = manager.control(row.id).state if data["active"] else None
    profile = store.get_profile(row.profile_id) if row.profile_id else None
    data["profile_name"] = profile.name if profile else ""
    return data


@router.get("/runs")
def list_runs(request: Request, status: str | None = None, app_id: int | None = None, limit: int = 50) -> list[dict]:
    rows = deps.store(request).list_runs(status=status, app_id=app_id, limit=min(max(limit, 1), 500))
    return [run_out(request, r) for r in rows]


@router.post("/runs", status_code=201)
def create_run(body: RunIn, request: Request) -> dict:
    user = getattr(request.state, "user", None)
    row = deps.manager(request).submit(RunRequest(**body.model_dump(), created_by=user.username if user else None))
    return run_out(request, row)


@router.get("/runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict:
    return run_out(request, deps.get_run_or_404(request, run_id))


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, request: Request):
    from fastapi import Response

    deps.get_run_or_404(request, run_id)
    manager = deps.manager(request)
    if manager.is_active(run_id):
        from qa_agent.agent.control import InterventionError

        raise InterventionError("Run masih berjalan. Hentikan dulu sebelum dihapus")
    manager.delete(run_id)
    return Response(status_code=204)


def state_snapshot(state, run_id: int) -> dict | None:
    """Snapshot kondisi run untuk REST dan WebSocket. `state` = app.state."""
    row = state.store.get_run(run_id)
    if row is None:
        return None
    snap = state.hub.snapshot(run_id)
    if snap["seq"] == 0:  # run lama / server baru start: bangun dari indeks
        snap.update(status=row.status, counts=row.counts, note=row.note)
        snap["cases"] = [{"tc_id": c.tc_id, "title": c.title, "status": c.effective_status}
                         for c in state.store.list_cases(run_id)]
    manager = state.manager
    snap["confirm_each_step"] = bool(row.options.get("confirm_each_step"))
    if manager.is_active(run_id):
        try:
            control = manager.control(run_id)
            snap["control_state"] = control.state
            snap["awaiting_confirm"] = control.awaiting_confirm
            return snap
        except Exception:
            pass
    snap["control_state"] = None
    snap["awaiting_confirm"] = False
    return snap


@router.get("/runs/{run_id}/state")
def run_state(run_id: int, request: Request) -> dict:
    snap = state_snapshot(request.app.state, run_id)
    if snap is None:
        raise deps.not_found("Run")
    return snap


@router.post("/runs/{run_id}/control")
def control_run(run_id: int, body: ControlIn, request: Request) -> dict:
    deps.get_run_or_404(request, run_id)
    return deps.manager(request).command(run_id, body.command, text=body.text, status=body.status, note=body.note,
                                         event=body.event)


def _plan_out(request: Request, run_id: int) -> dict:
    from pathlib import Path

    from qa_agent.evidence import RunStore

    row = deps.get_run_or_404(request, run_id)
    manager = deps.manager(request)
    app_map = RunStore(Path(row.folder)).read_app_map()
    screens = [{"url": s.url, "page_name": s.page_name} for s in (app_map.screens_for(row.module or "") if app_map else [])]
    return {"editable": manager.plan_editable(run_id), "module": row.module,
            "cases": [c.model_dump() for c in manager.plan(run_id)], "screens": screens}


@router.get("/runs/{run_id}/plan")
def get_plan(run_id: int, request: Request) -> dict:
    """Test case hasil susunan AI untuk direview sebelum dijalankan, beserta layar modul (pilihan layar awal)."""
    return _plan_out(request, run_id)


@router.put("/runs/{run_id}/plan")
def put_plan(run_id: int, body: PlanIn, request: Request) -> dict:
    from qa_agent.agent.control import InterventionError
    from qa_agent.models import QaTestCase

    plan = _plan_out(request, run_id)
    if not plan["editable"]:
        raise InterventionError("Test case hanya bisa diubah sebelum dijalankan")
    if not body.cases:
        raise ValueError("Minimal satu test case")
    screens = {s["url"] for s in plan["screens"]}
    cases = []
    for n, c in enumerate(body.cases, 1):
        steps = [s.strip() for s in c.steps if s.strip()]
        if not c.title.strip() or not steps or not c.expected.strip():
            raise ValueError(f"Test case ke-{n}: judul, langkah, dan expected result wajib diisi")
        if screens and c.start_url not in screens:
            raise ValueError(f"Test case ke-{n}: Layar awal harus salah satu layar modul ini")
        cases.append(QaTestCase(id=c.id or f"NEW-{n}", module=plan["module"] or "", page=c.page.strip(),
                                title=c.title.strip(), type=c.type, priority=c.priority,
                                precondition=c.precondition.strip(), test_data=c.test_data.strip(), steps=steps,
                                expected=c.expected.strip(), expected_source=c.expected_source, start_url=c.start_url))
    deps.manager(request).update_plan(run_id, cases)
    return _plan_out(request, run_id)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, request: Request) -> dict:
    deps.get_run_or_404(request, run_id)
    return run_out(request, deps.manager(request).resume(run_id))
