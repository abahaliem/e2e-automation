from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import ValidationError

from qa_agent.evidence import module_abbr
from qa_agent.models import STATUSES, TC_TYPES, AppMap, QaTestCase, RunMeta, StepRecord
from qa_agent.report.humanize import humanize, signal_text

# Mockup 09 (disepakati): 12 kolom
TC_HEADERS = ["TC ID", "Modul", "Skenario", "Tipe", "Prioritas", "Langkah", "Expected Result", "Actual Result",
              "Status AI", "Status Final", "Catatan Reviewer", "Evidence"]
TYPE_LABEL = {"positif": "Positif", "negatif": "Negatif", "validasi": "Validasi", "boundary": "Boundary",
              "navigasi": "Navigasi"}

# Nama kolom di template Excel kantor → kolom standar QA Agent
_ALIASES: dict[str, tuple[str, ...]] = {
    "TC ID": ("tc id", "id", "no tc", "no. tc", "nomor tc", "id test case", "test case id", "kode tc", "kode test case"),
    "Modul": ("modul", "module", "fitur", "menu"),
    "Halaman": ("halaman", "page", "layar", "screen"),
    "Skenario": ("skenario", "skenario pengujian", "scenario", "judul", "test case", "nama test case", "deskripsi"),
    "Tipe": ("tipe", "type", "jenis", "jenis pengujian"),
    "Prioritas": ("prioritas", "priority"),
    "Pre-condition": ("pre-condition", "precondition", "prasyarat", "kondisi awal"),
    "Test Data": ("test data", "data uji", "data"),
    "Langkah": ("langkah", "langkah pengujian", "steps", "test steps", "step"),
    "Expected Result": ("expected result", "expected", "hasil yang diharapkan", "hasil diharapkan", "ekspektasi"),
    "Sumber Expected": ("sumber expected",),
    "Actual Result": ("actual result", "actual", "hasil aktual", "hasil sebenarnya", "hasil"),
    "Status AI": ("status ai",),
    "Status Final": ("status final", "status akhir", "status", "hasil uji", "result", "pass/fail"),
    "Catatan Reviewer": ("catatan reviewer", "catatan", "keterangan", "remarks", "notes", "komentar"),
    "Severity": ("severity", "tingkat keparahan"),
    "Evidence": ("evidence", "bukti", "screenshot", "lampiran"),
    "URL Awal": ("url awal", "url"),
}
_ALIAS_INDEX = {re.sub(r"[^a-z0-9/]+", " ", alias).strip(): canonical for canonical, aliases in _ALIASES.items()
                for alias in aliases}


def canonical_header(name: object) -> str | None:
    """Nama kolom (bebas, dari template kantor) → nama kolom standar, atau None bila tidak dikenal."""
    if name is None:
        return None
    key = re.sub(r"[^a-z0-9/]+", " ", str(name).lower()).strip()
    return _ALIAS_INDEX.get(key)
PLAN_HEADERS = ["TC ID", "Modul", "Halaman", "Skenario", "Tipe", "Prioritas", "Pre-condition", "Test Data", "Langkah",
                "Expected Result", "Sumber Expected", "URL Awal"]
FINDING_HEADERS = ["ID Temuan", "TC ID", "Judul", "Severity", "Status", "Langkah Reproduksi", "Expected", "Actual",
                   "Sinyal Teknis", "Evidence"]
INVENTORY_HEADERS = ["Modul", "Halaman", "URL", "Fungsi", "Form & Field", "Aksi", "Akses", "Screenshot"]

STATUS_FILL = {"Pass": "C6EFCE", "Fail": "FFC7CE", "Perlu Review": "FFEB9C", "Blocked": "D9D9D9", "Skipped": "D9D9D9"}
HEADER_FILL = PatternFill("solid", fgColor="2560E8")  # aksen QA Agent (mockup 09)
WRAP = Alignment(wrap_text=True, vertical="top")
WIDE = {"Skenario": 36, "Langkah": 48, "Expected Result": 36, "Actual Result": 36, "Pre-condition": 24, "Test Data": 24,
        "Catatan Reviewer": 30, "Langkah Reproduksi": 48, "Expected": 32, "Actual": 32, "Sinyal Teknis": 40,
        "Judul": 36, "Fungsi": 36, "Form & Field": 40, "Aksi": 30, "URL": 36, "URL Awal": 36}


class ReportLockedError(Exception):
    """File laporan sedang dibuka aplikasi lain (biasanya Excel)."""


def _save(wb: Workbook, path: Path) -> None:
    try:
        wb.save(path)
    except PermissionError as e:
        raise ReportLockedError(f"Tidak bisa menulis {Path(path).name}. Tutup file itu di Excel lalu jalankan ulang perintahnya.") from e


def _clean(value: object) -> object:
    return ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value


def _append(ws: Worksheet, values: list | tuple) -> None:
    """Tambah baris: karakter kontrol dibuang, teks berawalan '=' disimpan sebagai teks (bukan formula)."""
    ws.append([_clean(v) for v in values])
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"


def _header(ws: Worksheet, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = WRAP
    for i, name in enumerate(headers, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = WIDE.get(name, 16)
    ws.freeze_panes = "A2"


def steps_text(steps: list[str]) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def parse_steps(text: str | None) -> list[str]:
    lines = [re.sub(r"^\s*\d+\s*[.)]\s*", "", line).strip() for line in (text or "").splitlines()]
    return [line for line in lines if line]


def _steps_for(tc_id: str, steps: list[StepRecord]) -> list[StepRecord]:
    return [s for s in steps if s.tc_id == tc_id]


def _last_screenshot(records: list[StepRecord]) -> str | None:
    return next((r.screenshot for r in reversed(records) if r.screenshot), None)


def _duration(meta: RunMeta) -> str:
    if not meta.finished_at:
        return "-"
    seconds = int((datetime.fromisoformat(meta.finished_at) - datetime.fromisoformat(meta.started_at)).total_seconds())
    return f"{seconds // 60} menit {seconds % 60} detik"


def _write_summary(ws: Worksheet, meta: RunMeta, cases: list[QaTestCase]) -> None:
    rows = [("Target", meta.target), ("Mode", meta.mode), ("Modul", meta.module or "-"), ("Environment", meta.environment),
            ("Model AI", meta.model), ("Mulai", meta.started_at), ("Selesai", meta.finished_at or "-"),
            ("Durasi", _duration(meta)), ("Status run", meta.status)]
    if meta.note:
        rows.append(("Catatan", meta.note))
    for row in rows:
        _append(ws, row)
    if cases:
        _append(ws, [])
        _append(ws, ["Status", "Jumlah (AI)", "Jumlah (Final)"])
        ai = Counter(c.status_ai for c in cases)
        final = Counter(c.effective_status for c in cases)
        for status in STATUSES:
            _append(ws, [status, ai.get(status, 0), final.get(status, 0)])
        _append(ws, ["Belum dijalankan", ai.get(None, 0), final.get(None, 0)])
        _append(ws, ["Total", len(cases), len(cases)])
        _append(ws, ["Pass rate", f"{round(100 * final.get('Pass', 0) / len(cases))}%"])
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 16


def _steps_cell(tc: QaTestCase) -> str:
    """Langkah + pre-condition/test data (mockup 09 tidak punya kolom terpisah, isinya tidak boleh hilang)."""
    parts = []
    if tc.precondition:
        parts.append(f"Pre-condition: {tc.precondition}")
    if tc.steps:
        parts.append(steps_text(tc.steps))
    if tc.test_data:
        parts.append(f"Test data: {tc.test_data}")
    return "\n".join(parts)


def case_values(tc: QaTestCase, *, generic_status: bool = False) -> dict[str, object]:
    """Nilai setiap kolom standar untuk satu test case."""
    return {
        "TC ID": tc.id, "Modul": tc.module, "Halaman": tc.page, "Skenario": tc.title,
        "Tipe": TYPE_LABEL.get(tc.type, tc.type), "Prioritas": tc.priority, "Pre-condition": tc.precondition,
        "Test Data": tc.test_data, "Langkah": _steps_cell(tc), "Expected Result": tc.expected,
        "Sumber Expected": tc.expected_source, "Actual Result": tc.actual, "Status AI": tc.status_ai or "",
        # Template kantor dengan satu kolom "Status": tampilkan status efektif (final bila ada, selain itu AI)
        "Status Final": (tc.effective_status if generic_status else tc.status_final) or "",
        "Catatan Reviewer": tc.reviewer_note, "Severity": tc.severity or "", "URL Awal": tc.start_url,
        "Evidence": None,
    }


def _fill_case_row(ws: Worksheet, row: int, columns: list[str | None], tc: QaTestCase, steps: list[StepRecord],
                   generic_status: bool = False) -> None:
    values = case_values(tc, generic_status=generic_status)
    shot = _last_screenshot(_steps_for(tc.id, steps))
    for i, key in enumerate(columns, 1):
        if key is None:
            continue
        cell = ws.cell(row, i, _clean(values.get(key)))
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"
        cell.alignment = WRAP
        if key in ("Status AI", "Status Final") and cell.value in STATUS_FILL:
            cell.fill = PatternFill("solid", fgColor=STATUS_FILL[cell.value])
        if key == "Evidence" and shot:
            cell.value = "Lihat screenshot"
            cell.hyperlink = shot
            cell.style = "Hyperlink"


def _status_validation(ws: Worksheet, columns: list[str | None]) -> None:
    if "Status Final" not in columns:
        return
    dv = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
    ws.add_data_validation(dv)
    column = ws.cell(1, columns.index("Status Final") + 1).column_letter
    dv.add(f"{column}2:{column}{max(ws.max_row, 2)}")


def _write_cases(ws: Worksheet, cases: list[QaTestCase], steps: list[StepRecord]) -> None:
    _header(ws, TC_HEADERS)
    columns: list[str | None] = list(TC_HEADERS)
    for row, tc in enumerate(cases, start=2):
        _fill_case_row(ws, row, columns, tc, steps)
    _status_validation(ws, columns)


def _template_sheet(template: Path) -> tuple[Workbook, Worksheet, list[str | None]]:
    """Buka template kantor: sheet dengan header paling banyak dikenali menjadi sheet Test Cases."""
    try:
        wb = load_workbook(template)
    except Exception as e:  # file rusak / bukan xlsx
        raise ValueError(f"Template Excel tidak bisa dibuka: {e}") from e
    best, best_score = wb.worksheets[0], -1
    for ws in wb.worksheets:
        score = sum(1 for c in ws[1] if canonical_header(c.value))
        if score > best_score:
            best, best_score = ws, score
    if best_score < 2:
        raise ValueError("Template Excel harus punya baris judul kolom (mis. TC ID, Skenario, Expected Result)")
    for ws in list(wb.worksheets):
        if ws is not best:
            wb.remove(ws)
    best.title = "Test Cases"
    if best.max_row > 1:
        best.delete_rows(2, best.max_row - 1)
    columns = [canonical_header(c.value) for c in best[1]]
    return wb, best, columns


def _write_findings(ws: Worksheet, cases: list[QaTestCase], steps: list[StepRecord]) -> None:
    _header(ws, FINDING_HEADERS)
    n = 0
    for tc in cases:
        if tc.effective_status not in ("Fail", "Perlu Review"):
            continue
        n += 1
        records = _steps_for(tc.id, steps)
        repro = [humanize(r.action, r.element, r.value) for r in records if r.action not in ("done", "blocked", "invalid", "hint")]
        signals: list[str] = []
        for r in records:
            for s in r.signals:
                if s.kind in ("http_error", "page_error", "console_error") and signal_text(s) not in signals:
                    signals.append(signal_text(s))
        _append(ws, [f"BUG-{n:03d}", tc.id, tc.title, tc.severity or "", tc.effective_status, steps_text(repro),
                   tc.expected, tc.actual, "\n".join(signals[:5]), None])
        row = ws.max_row
        for cell in ws[row]:
            cell.alignment = WRAP
        shot = _last_screenshot(records)
        if shot:
            cell = ws.cell(row, len(FINDING_HEADERS), "Lihat screenshot")
            cell.hyperlink = shot
            cell.style = "Hyperlink"


def _write_inventory(ws: Worksheet, app_map: AppMap) -> None:
    _header(ws, INVENTORY_HEADERS)
    for s in app_map.screens:
        forms = "\n".join(
            f"{f.get('name', 'Form')}: " + ", ".join(f"{fd.get('label', '?')} ({fd.get('type', '?')})" for fd in f.get("fields", []))
            for f in s.forms)
        _append(ws, [s.module, s.page_name, s.url, s.purpose, forms, ", ".join(s.actions), "Publik" if s.public else "Login", None])
        row = ws.max_row
        for cell in ws[row]:
            cell.alignment = WRAP
        if s.screenshot:
            cell = ws.cell(row, len(INVENTORY_HEADERS), "Lihat screenshot")
            cell.hyperlink = s.screenshot
            cell.style = "Hyperlink"


def write_report_xlsx(path: Path, meta: RunMeta, cases: list[QaTestCase], steps: list[StepRecord], app_map: AppMap | None,
                      template: Path | None = None) -> None:
    """Laporan Excel. `template` = template Excel kantor (opsional) yang menentukan kolom sheet Test Cases."""
    if template is not None and cases:
        wb, ws, columns = _template_sheet(Path(template))
        generic = "Status AI" not in columns
        for row, tc in enumerate(cases, start=2):
            _fill_case_row(ws, row, columns, tc, steps, generic_status=generic)
        _status_validation(ws, columns)
        ws.freeze_panes = "A2"
        summary = wb.create_sheet("Ringkasan", 0)
        _write_summary(summary, meta, cases)
        _write_findings(wb.create_sheet("Temuan"), cases, steps)
    else:
        wb = Workbook()
        summary = wb.active
        summary.title = "Ringkasan"
        _write_summary(summary, meta, cases)
        if cases:
            _write_cases(wb.create_sheet("Test Cases"), cases, steps)
            _write_findings(wb.create_sheet("Temuan"), cases, steps)
    if app_map and app_map.screens:
        _write_inventory(wb.create_sheet("Inventaris Fitur"), app_map)
    _save(wb, Path(path))


def write_cases_xlsx(path: Path, cases: list[QaTestCase]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    _header(ws, PLAN_HEADERS)
    for tc in cases:
        _append(ws, [tc.id, tc.module, tc.page, tc.title, tc.type, tc.priority, tc.precondition, tc.test_data,
                   steps_text(tc.steps), tc.expected, tc.expected_source, tc.start_url])
        for cell in ws[ws.max_row]:
            cell.alignment = WRAP
    for header, options in (("Tipe", TC_TYPES), ("Prioritas", ("High", "Medium", "Low")), ("Sumber Expected", ("PRD", "Inferensi AI"))):
        dv = DataValidation(type="list", formula1=f'"{",".join(options)}"', allow_blank=True)
        ws.add_data_validation(dv)
        column = ws.cell(1, PLAN_HEADERS.index(header) + 1).column_letter
        dv.add(f"{column}2:{column}500")
    _save(wb, Path(path))


def _rows(path: Path) -> list[tuple[int, dict[str, object]]]:
    wb = load_workbook(path)
    if "Test Cases" not in wb.sheetnames:
        return []
    ws = wb["Test Cases"]
    headers = [canonical_header(c.value) or c.value for c in ws[1]]  # template kantor → nama standar
    out = []
    for row_no, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v in (None, "") for v in values):
            continue
        out.append((row_no, dict(zip(headers, values))))
    return out


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def import_cases_xlsx(path: Path) -> list[QaTestCase]:
    rows = _rows(path)
    cases: list[QaTestCase] = []
    used = {_text(r.get("TC ID")) for _, r in rows if _text(r.get("TC ID"))}
    for row_no, r in rows:
        tc_id = _text(r.get("TC ID"))
        module = _text(r.get("Modul"))
        if not tc_id:  # baris baru dari reviewer → nomor setelah nomor terbesar
            prefix = f"TC-{module_abbr(module)}-"
            numbers = [int(u[len(prefix):]) for u in used if u.startswith(prefix) and u[len(prefix):].isdigit()]
            tc_id = f"{prefix}{max(numbers, default=0) + 1:03d}"
            used.add(tc_id)
        try:
            cases.append(QaTestCase(
                id=tc_id, module=module, page=_text(r.get("Halaman")), title=_text(r.get("Skenario")),
                type=_text(r.get("Tipe")).lower() or "positif", priority=_text(r.get("Prioritas")).capitalize() or "Medium",
                precondition=_text(r.get("Pre-condition")), test_data=_text(r.get("Test Data")),
                steps=parse_steps(_text(r.get("Langkah"))), expected=_text(r.get("Expected Result")),
                expected_source="PRD" if _text(r.get("Sumber Expected")).upper() == "PRD" else "Inferensi AI",
                start_url=_text(r.get("URL Awal")),
            ))
        except ValidationError as e:
            err = e.errors()[0]
            raise ValueError(f"Baris {row_no}: kolom '{err['loc'][0]}' tidak valid ({err['msg']})") from e
    return cases


def read_review(path: Path) -> dict[str, dict]:
    canonical = {s.lower(): s for s in STATUSES}
    review: dict[str, dict] = {}
    for row_no, r in _rows(path):
        tc_id = _text(r.get("TC ID"))
        if not tc_id:
            continue
        raw = _text(r.get("Status Final"))
        status = canonical.get(raw.lower()) if raw else None
        if raw and status is None:
            raise ValueError(f"Baris {row_no}: Status Final '{raw}' tidak dikenal. Pilihan: {', '.join(STATUSES)}")
        review[tc_id] = {"status_final": status, "reviewer_note": _text(r.get("Catatan Reviewer"))}
    return review
