"""Dokumen PDF laporan sesuai mockup 08: HTML cetak khusus (gambar tertanam) lalu dicetak Chromium."""
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from qa_agent.evidence import RunStore
from qa_agent.models import QaTestCase, StepRecord
from qa_agent.report.build import apply_review
from qa_agent.report.excel import TYPE_LABEL
from qa_agent.report.humanize import humanize, signal_text

_ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html", "j2"]))
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]
CSS = {"Pass": "pass", "Fail": "fail", "Perlu Review": "review", "Blocked": "blocked", "Skipped": "blocked"}
NON_REPRO = {"done", "blocked", "invalid", "hint"}


def _date(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}, {d.hour:02d}.{d.minute:02d}"


def _duration(start: str, end: str | None) -> str:
    if not end:
        return "-"
    secs = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    if secs < 60:
        return f"{secs} detik"
    hours, minutes = divmod(secs // 60, 60)
    return f"{hours} jam {minutes} menit" if hours else f"{minutes} menit"


def _image(root: Path, rel: str | None) -> str | None:
    if not rel:
        return None
    path = root / rel
    if not path.is_file():
        return None
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def summary_sentence(cases: list[QaTestCase]) -> str:
    executed = [c for c in cases if c.effective_status and c.effective_status != "Skipped"]
    passed = sum(1 for c in executed if c.effective_status == "Pass")
    rate = round(100 * passed / len(executed)) if executed else 0
    fails = [c for c in cases if c.effective_status == "Fail"]
    reviews = [c for c in cases if c.effective_status == "Perlu Review"]
    blocked = [c for c in cases if c.effective_status in ("Blocked", "Skipped")]
    parts = [f"Pass rate {rate}%."]
    if fails:
        names = "; ".join(c.title for c in fails[:3]) + ("; dan lainnya" if len(fails) > 3 else "")
        parts.append(f"Ditemukan {len(fails)} bug: {names}.")
    else:
        parts.append("Tidak ada test case yang Fail.")
    if reviews:
        parts.append(f"{len(reviews)} test case perlu direview karena hasilnya berbeda dari expected hasil inferensi AI.")
    if blocked:
        parts.append(f"{len(blocked)} test case tidak dieksekusi penuh (diblok atau dilewati).")
    return " ".join(parts)


def _finding(n: int, tc: QaTestCase, records: list[StepRecord], root: Path) -> dict:
    repro = [humanize(r.action, r.element, r.value) for r in records if r.action not in NON_REPRO] or list(tc.steps)
    technical: list[str] = []
    for r in records:
        for s in r.signals:
            if s.kind in ("http_error", "page_error", "console_error") and signal_text(s) not in technical:
                technical.append(signal_text(s))
    shot = next((r for r in reversed(records) if r.screenshot), None)
    action = next((r for r in reversed(records) if r.action not in NON_REPRO), None)
    caption = f"Setelah: {humanize(action.action, action.element, action.value)}" if action else ""
    status = tc.effective_status or ""
    return {
        "code": f"BUG-{n:03d}", "tc_id": tc.id, "title": tc.title, "status": status,
        "badge": f"{status}, {tc.severity}" if tc.severity and status == "Fail" else status,
        "repro": repro, "expected": tc.expected, "actual": tc.actual, "technical": technical[:4],
        "note": tc.reviewer_note, "image": _image(root, shot.screenshot if shot else None),
        "caption": caption,
    }


def render_pdf_html(store: RunStore, *, app_name: str = "", run_id: int | None = None, company: str = "",
                    logo: str | None = None) -> str:
    """`logo`: data URI PNG logo perusahaan (Pengaturan > Laporan) untuk kepala dokumen."""
    meta = store.read_meta()
    cases = store.read_testcases()
    apply_review(cases, store.read_review())
    steps = store.read_steps()
    app_map = store.read_app_map()
    findings_cases = [c for c in cases if c.effective_status in ("Fail", "Perlu Review")]
    reviewed = sum(1 for c in findings_cases if c.status_final)
    parts = urlsplit(meta.target)
    started = datetime.fromisoformat(meta.started_at)
    counts = {"total": len(cases), "Pass": 0, "Fail": 0, "Review": 0, "Blocked": 0}
    for c in cases:
        key = {"Perlu Review": "Review", "Skipped": None}.get(c.effective_status or "", c.effective_status)
        if key in counts:
            counts[key] += 1
    name = app_name or parts.netloc or meta.target
    context = {
        "company": company,
        "logo": logo,
        "run_code": f"RUN-{started:%Y%m%d-%H%M}" + (f" #{run_id}" if run_id else ""),
        "subtitle": f"{name}, modul {meta.module}" if meta.module else f"{name}, seluruh aplikasi",
        "target": parts.netloc + (parts.path if parts.scheme == "android" else "") or meta.target,
        "environment": "Production" if meta.environment == "production" else "Dev / UAT",
        "tested_at": _date(meta.started_at),
        "duration": _duration(meta.started_at, meta.finished_at),
        "model": meta.model,
        "review_status": f"{reviewed} dari {len(findings_cases)} temuan sudah direview" if findings_cases else "Tidak ada temuan",
        "counts": counts,
        "summary": summary_sentence(cases) if cases else "",
        "findings": [_finding(i, tc, [s for s in steps if s.tc_id == tc.id], store.root)
                     for i, tc in enumerate(findings_cases, 1)],
        "cases": [{"id": c.id, "title": c.title, "type_label": TYPE_LABEL.get(c.type, c.type),
                   "status": c.effective_status or "Belum dijalankan", "css": CSS.get(c.effective_status or "", "blocked")}
                  for c in cases],
        "screens": app_map.screens if app_map else [],
        "modules": app_map.modules() if app_map else [],
    }
    return _ENV.get_template("report_pdf.html.j2").render(**context)


def write_report_pdf(store: RunStore, pdf_path: Path, **kw) -> Path:
    """Tulis report_pdf.html lalu cetak menjadi PDF A4 dengan nomor halaman."""
    from qa_agent.report.pdf import html_to_pdf

    html_path = store.root / "report_pdf.html"
    html_path.write_text(render_pdf_html(store, **kw), encoding="utf-8")
    return html_to_pdf(html_path, Path(pdf_path), page_numbers=True)
