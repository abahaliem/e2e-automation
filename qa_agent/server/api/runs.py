from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from qa_agent.server.api import deps
from qa_agent.server.runs import RunRequest
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
    row = deps.manager(request).submit(RunRequest(**body.model_dump()))
    return run_out(request, row)


@router.get("/runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict:
    return run_out(request, deps.get_run_or_404(request, run_id))


@router.get("/runs/{run_id}/state")
def run_state(run_id: int, request: Request) -> dict:
    row = deps.get_run_or_404(request, run_id)
    snap = deps.hub(request).snapshot(run_id)
    if snap["seq"] == 0:  # run lama / server baru start: bangun dari indeks
        snap.update(status=row.status, counts=row.counts, note=row.note)
        snap["cases"] = [{"tc_id": c.tc_id, "title": c.title, "status": c.effective_status}
                         for c in deps.store(request).list_cases(run_id)]
    manager = deps.manager(request)
    if manager.is_active(run_id):
        control = manager.control(run_id)
        snap["control_state"] = control.state
        snap["awaiting_confirm"] = control.awaiting_confirm
    else:
        snap["control_state"] = None
        snap["awaiting_confirm"] = False
    return snap


@router.post("/runs/{run_id}/control")
def control_run(run_id: int, body: ControlIn, request: Request) -> dict:
    deps.get_run_or_404(request, run_id)
    return deps.manager(request).command(run_id, body.command, text=body.text, status=body.status, note=body.note,
                                         event=body.event)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, request: Request) -> dict:
    deps.get_run_or_404(request, run_id)
    return run_out(request, deps.manager(request).resume(run_id))
