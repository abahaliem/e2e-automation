from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from qa_agent.evidence import RunStore, slugify
from qa_agent.models import STATUSES, QaTestCase
from qa_agent.report.build import apply_review, import_review
from qa_agent.server.reporting import build_run_reports, company_name
from qa_agent.report.excel import ReportLockedError
from qa_agent.report.humanize import humanize, signal_text
from qa_agent.server.api import deps

router = APIRouter(prefix="/api", tags=["results"])
LOCKED_WARNING = ("Tutup report.xlsx di Excel supaya laporan bisa diperbarui. "
                  "Review sudah tersimpan dan akan masuk ke laporan saat dibuat ulang.")

Status = Literal["Pass", "Fail", "Perlu Review", "Blocked", "Skipped"]


class ReviewIn(BaseModel):
    status_final: Status | None = None
    severity: Literal["Critical", "Major", "Minor"] | None = None
    reviewer_note: str | None = Field(default=None, max_length=4000)


def _run_store(request: Request, run_id: int) -> RunStore:
    row = deps.get_run_or_404(request, run_id)
    folder = Path(row.folder)
    if not folder.is_dir():
        raise deps.not_found("Folder run")
    return RunStore(folder)


def _cases(rs: RunStore) -> list[QaTestCase]:
    cases = rs.read_testcases()
    apply_review(cases, rs.read_review())
    return cases


def _case_out(tc: QaTestCase) -> dict:
    return {**tc.model_dump(), "effective_status": tc.effective_status}


@router.get("/runs/{run_id}/cases")
def list_cases(run_id: int, request: Request) -> list[dict]:
    return [_case_out(tc) for tc in _cases(_run_store(request, run_id))]


@router.get("/runs/{run_id}/cases/{tc_id}")
def case_detail(run_id: int, tc_id: str, request: Request) -> dict:
    rs = _run_store(request, run_id)
    tc = next((c for c in _cases(rs) if c.id == tc_id), None)
    if tc is None:
        raise deps.not_found("Test case")
    log, technical = [], []
    for s in rs.read_steps():
        if s.tc_id != tc_id:
            continue
        log.append({
            "step_no": s.step_no, "action": s.action, "actor": s.actor,
            "text": humanize(s.action, s.element, s.value), "result": s.result, "guard": s.guard,
            "thought": s.thought, "location": s.location,
            "screenshot_url": f"/api/runs/{run_id}/files/{s.screenshot}" if s.screenshot else None,
        })
        for sig in s.signals:
            text = signal_text(sig)
            if text not in technical:
                technical.append(text)
    # "steps" = langkah rencana test case; "log" = langkah yang benar-benar dijalankan (evidence)
    return {**_case_out(tc), "log": log, "technical": technical}


@router.patch("/runs/{run_id}/cases/{tc_id}")
def review_case(run_id: int, tc_id: str, body: ReviewIn, request: Request) -> dict:
    rs = _run_store(request, run_id)
    if not any(c.id == tc_id for c in rs.read_testcases()):
        raise deps.not_found("Test case")
    # 1) Editan reviewer di Excel yang lebih baru diimpor dulu supaya tidak hilang.
    try:
        from qa_agent.report.build import excel_is_newer

        if excel_is_newer(rs):
            import_review(rs)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile):
        pass
    # 2) Terapkan review dari dashboard ke review.json (sumber kebenaran).
    review = rs.read_review()
    entry = dict(review.get(tc_id) or {"status_final": None, "reviewer_note": ""})
    for key, value in body.model_dump(exclude_unset=True).items():
        entry[key] = value if key != "reviewer_note" else (value or "")
    review[tc_id] = entry
    rs.write_review(review)
    # 3) Bangun ulang laporan tanpa mengimpor Excel lagi.
    warning = None
    try:
        build_run_reports(rs, deps.store(request), deps.settings(request), import_excel=False)
    except ReportLockedError:
        warning = LOCKED_WARNING
    cases = _cases(rs)
    store = deps.store(request)
    store.upsert_cases(run_id, cases)
    counts = {s: n for s in STATUSES if (n := sum(1 for c in cases if c.effective_status == s))}
    store.update_run(run_id, counts=counts)
    tc = next(c for c in cases if c.id == tc_id)
    return {"case": _case_out(tc), "warning": warning}


@router.get("/runs/{run_id}/files/{path:path}")
def run_file(run_id: int, path: str, request: Request) -> FileResponse:
    rs = _run_store(request, run_id)
    root = rs.root.resolve()
    try:
        target = (root / path).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        raise deps.not_found("File")
    if not target.is_file():
        raise deps.not_found("File")
    return FileResponse(target)


@router.get("/runs/{run_id}/thumbnail")
def run_thumbnail(run_id: int, request: Request) -> FileResponse:
    """Screenshot terbaru run (kartu Sedang berjalan di Dashboard)."""
    rs = _run_store(request, run_id)
    shots = list(rs.screenshots_dir.glob("*.png")) if rs.screenshots_dir.is_dir() else []
    if not shots:
        raise deps.not_found("Screenshot")
    latest = max(shots, key=lambda p: p.stat().st_mtime)
    return FileResponse(latest, media_type="image/png", headers={"cache-control": "no-store"})


@router.get("/runs/{run_id}/download/{kind}")
def download(run_id: int, kind: str, request: Request) -> FileResponse:
    if kind not in ("xlsx", "html", "pdf"):
        raise deps.not_found("Jenis dokumen")
    row = deps.get_run_or_404(request, run_id)
    rs = _run_store(request, run_id)
    if not rs.meta_path.exists():
        raise deps.not_found("Laporan")
    store, settings = deps.store(request), deps.settings(request)
    if not rs.report_xlsx.exists() or not rs.report_html.exists():
        try:
            build_run_reports(rs, store, settings)
        except ReportLockedError as e:
            raise HTTPException(status_code=409, detail=str(e))
    app = store.get_app(row.app_id)
    base = f"hasil-pengujian-{slugify(app.name if app else 'aplikasi')}-{slugify(row.module or row.mode)}-run{row.id}"
    if kind == "xlsx":
        return FileResponse(rs.report_xlsx, filename=f"{base}.xlsx",
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if kind == "html":
        return FileResponse(rs.report_html, filename=f"{base}.html", media_type="text/html")
    pdf = rs.root / "report.pdf"
    sources = [p for p in (rs.report_html, rs.review_path, rs.testcases_path) if p.exists()]
    stale = not pdf.exists() or any(p.stat().st_mtime > pdf.stat().st_mtime for p in sources)
    if stale:  # dokumen PDF sesuai mockup 08 (bukan cetakan report.html)
        from qa_agent.report.pdf_doc import write_report_pdf

        write_report_pdf(rs, pdf, app_name=app.name if app else "", run_id=row.id, company=company_name(store))
    return FileResponse(pdf, filename=f"{base}.pdf", media_type="application/pdf")
