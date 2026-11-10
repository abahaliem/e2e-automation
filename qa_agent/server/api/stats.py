from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from qa_agent.server.api import deps

router = APIRouter(prefix="/api", tags=["stats"])


class ImportIn(BaseModel):
    folder: str
    app_id: int


@router.get("/stats")
def stats(request: Request, days: int = 30) -> dict:
    days = min(max(days, 1), 36500)
    now = datetime.now() + timedelta(seconds=1)
    data = deps.store(request).stats(now - timedelta(days=days), now)
    store = deps.store(request)
    data["running"] = len(store.list_runs(status="running,paused,queued", limit=500))
    data["days"] = days
    return data


@router.get("/findings")
def findings(request: Request, limit: int = 10) -> list[dict]:
    return deps.store(request).latest_findings(limit=min(max(limit, 1), 100))


@router.post("/import-runs")
def import_runs(body: ImportIn, request: Request) -> dict:
    store = deps.store(request)
    if store.get_app(body.app_id) is None:
        raise deps.not_found("Aplikasi")
    folder = Path(body.folder.strip().strip('"'))
    if not folder.is_dir():
        raise deps.not_found("Folder")
    candidates = [folder] if (folder / "run.json").exists() else sorted(
        p for p in folder.iterdir() if p.is_dir() and (p / "run.json").exists())
    imported, failed = 0, []
    for path in candidates:
        try:
            store.import_run_folder(path, body.app_id)
            imported += 1
        except Exception as e:
            failed.append({"folder": str(path), "error": f"{type(e).__name__}: {e}"})
    return {"imported": imported, "failed": failed}
