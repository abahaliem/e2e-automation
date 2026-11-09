"""Penyimpanan file/teks skill QA di folder data dan penyusunan bagian prompt per run."""
from __future__ import annotations

from pathlib import Path

from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store
from qa_agent.skills import EXECUTE_STAGES, PLAN_STAGES, skill_section


def skills_dir(settings: ServerSettings) -> Path:
    return settings.data_dir / "skills"


def text_path(settings: ServerSettings, skill_id: int) -> Path:
    return skills_dir(settings) / f"{skill_id}.txt"


def read_text(settings: ServerSettings, skill_id: int) -> str:
    path = text_path(settings, skill_id)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def sections_for(store: Store, settings: ServerSettings, app_id: int) -> dict[str, str]:
    """Bagian '## Skill QA' untuk prompt PLAN dan EXECUTE (skill bawaan selalu ikut)."""
    out = {}
    for key, stages in (("plan", PLAN_STAGES), ("execute", EXECUTE_STAGES)):
        extra = [(s.name, read_text(settings, s.id)) for s in store.skills_for(app_id=app_id, stages=stages)]
        out[key] = skill_section([(n, t) for n, t in extra if t])
    return out
