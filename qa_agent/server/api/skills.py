"""Pengaturan > Skill QA (mockup 06)."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from qa_agent.evidence import RunStore
from qa_agent.llm.base import LLMError
from qa_agent.orchestrator.deep import DeepPlanner, PlanError
from qa_agent.server.api import deps
from qa_agent.server.skillbank import read_text, sections_for, skills_dir, text_path
from qa_agent.server.store import SkillRow
from qa_agent.skills import ALLOWED, BUILTIN_SKILL, MAX_BYTES, STAGES, SkillError, capacity_percent, extract_text

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    stages: list[str] | None = None
    app_ids: list[int] | None = None
    active: bool | None = None

    @field_validator("stages")
    @classmethod
    def _stages(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        bad = [s for s in v if s not in STAGES]
        if bad or not v:
            raise ValueError("Tahap harus salah satu dari: " + ", ".join(STAGES.values()))
        return [s for s in STAGES if s in v]


class PreviewIn(BaseModel):
    app_id: int
    module: str = Field(min_length=1)
    profile_id: int | None = None


def _out(request: Request, s: SkillRow) -> dict:
    store = deps.store(request)
    names = [a.name for a in (store.get_app(i) for i in s.app_ids) if a is not None]
    return {**s.model_dump(), "app_names": names, "stage_labels": [STAGES[x] for x in s.stages]}


def _title(text: str, filename: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"^[#\s>*-]+", "", line).strip()
        if line:
            return line[:120]
    return Path(filename).stem.replace("-", " ").replace("_", " ").strip().title() or "Skill"


@router.get("")
def list_skills(request: Request) -> dict:
    store = deps.store(request)
    skills = store.list_skills()
    used = len(BUILTIN_SKILL.content) + sum(s.chars for s in skills if s.active)
    return {
        "builtin": {"name": BUILTIN_SKILL.name, "description": BUILTIN_SKILL.description,
                    "topics": list(BUILTIN_SKILL.topics), "content": BUILTIN_SKILL.content},
        "skills": [_out(request, s) for s in skills],
        "stages": STAGES,
        "capacity_percent": max(1, capacity_percent(used)),
    }


@router.post("", status_code=201)
async def upload_skill(request: Request, filename: str = "skill.md"):
    def invalid(message: str) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": message, "field_errors": {"file": message}})

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        return invalid("Skill harus berupa file .md, .txt, .docx, atau .pdf")
    data = await request.body()
    if not data or len(data) > MAX_BYTES:
        return invalid("File skill kosong atau lebih dari 10 MB")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"skill{suffix}"
        path.write_bytes(data)
        try:
            text, pages = extract_text(path)
        except SkillError as e:
            return invalid(str(e))
    store, settings = deps.store(request), deps.settings(request)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-") or f"skill{suffix}"
    skill = store.create_skill(name=_title(text, filename), filename=Path(filename).name, pages=pages, chars=len(text),
                               stages=list(STAGES))
    folder = skills_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    text_path(settings, skill.id).write_text(text, encoding="utf-8")
    (folder / f"{skill.id}-{safe}").write_bytes(data)
    return _out(request, skill)


@router.patch("/{skill_id}")
def patch_skill(skill_id: int, body: SkillPatch, request: Request) -> dict:
    store = deps.store(request)
    if store.get_skill(skill_id) is None:
        raise deps.not_found("Skill")
    return _out(request, store.update_skill(skill_id, **body.model_dump(exclude_unset=True)))


@router.get("/{skill_id}/text")
def skill_text(skill_id: int, request: Request) -> dict:
    if deps.store(request).get_skill(skill_id) is None:
        raise deps.not_found("Skill")
    return {"text": read_text(deps.settings(request), skill_id)}


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: int, request: Request) -> Response:
    store, settings = deps.store(request), deps.settings(request)
    if store.get_skill(skill_id) is None:
        raise deps.not_found("Skill")
    store.delete_skill(skill_id)
    for path in skills_dir(settings).glob(f"{skill_id}[.-]*"):
        path.unlink(missing_ok=True)
    return Response(status_code=204)


@router.post("/preview")
def preview(body: PreviewIn, request: Request) -> dict:
    """'Coba pada modul contoh': susun test case (tanpa menjalankan) memakai skill aktif."""
    from qa_agent.server.api.profiles import client_for

    store, settings = deps.store(request), deps.settings(request)
    app = store.get_app(body.app_id)
    if app is None:
        raise deps.not_found("Aplikasi")
    explore = store.latest_completed_explore(app.id)
    app_map = RunStore(Path(explore.folder)).read_app_map() if explore else None
    if app_map is None:
        raise HTTPException(status_code=422, detail="Jalankan Seluruh aplikasi dulu untuk memetakan modul")
    profile = store.get_profile(body.profile_id) if body.profile_id else store.get_default_profile()
    if profile is None:
        raise HTTPException(status_code=422, detail="Belum ada profil AI")
    planner = DeepPlanner(client_for(request, profile), data_prefix="QA-AUTO-PREVIEW", max_tcs=5,
                          skills=sections_for(store, settings, app.id)["plan"])
    try:
        cases = planner.plan(app_map, body.module, (explore.options or {}).get("prd_text"))
    except PlanError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"Endpoint AI bermasalah: {e}")
    return {"cases": [c.model_dump(mode="json") for c in cases]}
