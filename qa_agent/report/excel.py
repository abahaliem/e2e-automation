from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, MergedCell
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
    "No": ("no", "no.", "nomor", "item", "item #", "item no", "#"),
    "Peran": ("user role", "role", "peran", "aktor", "actor", "peran pengguna"),
    "Modul": ("modul", "module", "fitur", "menu", "modul / menu", "modul/menu", "module / menu", "feature"),
    "Halaman": ("halaman", "page", "layar", "screen"),
    "Skenario": ("skenario", "skenario pengujian", "scenario", "judul", "test case", "nama test case", "deskripsi",
                 "business process", "proses bisnis", "test case description", "test case name", "test scenario"),
    "Tipe": ("tipe", "type", "jenis", "jenis pengujian"),
    "Prioritas": ("prioritas", "priority"),
    "Pre-condition": ("pre-condition", "precondition", "prasyarat", "kondisi awal"),
    "Test Data": ("test data", "data uji", "data"),
    "Langkah": ("langkah", "langkah pengujian", "steps", "test steps", "step", "steps to execute", "use case / scenario",
                "use case/scenario", "use case", "langkah langkah", "test procedure"),
    "Expected Result": ("expected result", "expected", "hasil yang diharapkan", "hasil diharapkan", "ekspektasi"),
    "Sumber Expected": ("sumber expected",),
    "Actual Result": ("actual result", "actual", "hasil aktual", "hasil sebenarnya", "hasil"),
    "Status AI": ("status ai",),
    "Status Final": ("status final", "status akhir", "status", "hasil uji", "result", "pass/fail"),
    "Catatan Reviewer": ("catatan reviewer", "catatan", "keterangan", "remarks", "notes", "komentar", "comments",
                         "comment"),
    "Severity": ("severity", "tingkat keparahan"),
    "Evidence": ("evidence", "bukti", "screenshot", "lampiran", "screenshot (url)", "screenshot url", "link evidence"),
    "Tanggal": ("test date", "tanggal", "tanggal uji", "tanggal pengujian", "date", "tested on"),
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
                   generic_status: bool = False, vocab: list[str] | None = None, extra: dict | None = None) -> None:
    values = {**case_values(tc, generic_status=generic_status), **(extra or {})}
    shot = _last_screenshot(_steps_for(tc.id, steps))
    for i, key in enumerate(columns, 1):
        if key is None:
            continue
        value = values.get(key)
        standard = value if key in ("Status AI", "Status Final") else None
        if key == "Status Final" and vocab:
            value = status_from_vocab(value or None, vocab)  # kosakata template kantor (Passed, ✓, ...)
        cell = ws.cell(row, i, _clean(value))
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"
        cell.alignment = WRAP
        if standard in STATUS_FILL:
            cell.fill = PatternFill("solid", fgColor=STATUS_FILL[standard])
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


def _status_validation_at(ws: Worksheet, info: "TemplateInfo") -> None:
    """Template tanpa daftar status: tambahkan pilihan status standar di kolom Status."""
    if "Status Final" not in info.columns:
        return
    from openpyxl.utils import get_column_letter

    dv = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
    ws.add_data_validation(dv)
    column = get_column_letter(info.columns.index("Status Final") + 1)
    last = info.footer_row - 1 if info.footer_row else max(ws.max_row, info.data_row)
    dv.add(f"{column}{info.data_row}:{column}{max(last, info.data_row)}")


def _write_cases(ws: Worksheet, cases: list[QaTestCase], steps: list[StepRecord]) -> None:
    _header(ws, TC_HEADERS)
    columns: list[str | None] = list(TC_HEADERS)
    for row, tc in enumerate(cases, start=2):
        _fill_case_row(ws, row, columns, tc, steps)
    _status_validation(ws, columns)


# ---------------------------------------------------------------- template kantor dengan tata letak bebas
HEADER_SCAN_ROWS = 40
_FOOTER = re.compile(r"rekap|total|kesimpulan|summary|signature|tanda tangan|approved|prepared by|reviewed by|"
                     r"catatan tambahan|rekomendasi|conclusion", re.IGNORECASE)
# Isian kepala dokumen (label → kunci); hanya diisi bila selnya masih kosong / berisi ":" saja
_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "project": ("project name", "project", "nama proyek", "proyek", "nama aplikasi", "application", "aplikasi"),
    "date": ("uat date", "test date", "tanggal", "tanggal uji", "tanggal pengujian", "last update", "date"),
    "developer": ("developer", "pengembang"),
    "version": ("version (app/system)", "version", "versi", "app version", "versi aplikasi"),
    "tester": ("qa/tester", "qa / tester", "tester", "qa", "penguji"),
    "segment": ("segment", "segmen"),
    "user": ("user", "pengguna", "user representative"),
    "platform": ("platform",),
    "environment": ("environment", "lingkungan"),
}
_FIELD_INDEX = {re.sub(r"[^a-z0-9/()]+", " ", a).strip(): k for k, aliases in _FIELD_KEYS.items() for a in aliases}
_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
           "November", "Desember"]


@dataclass
class TemplateField:
    label: str  # teks label di template, mis. "Project Name"
    key: str  # project | date | developer | version | tester | segment | user | platform | environment
    row: int
    value_col: int
    prefix: str  # ": " bila sel isian berformat ": nilai"


@dataclass
class TemplateInfo:
    sheet: str
    header_row: int
    columns: list[str | None]  # per kolom (1-based → index 0); None = kolom tidak dikenali / bagian sel gabungan
    headers: list[object]
    capacity: int | None  # jumlah baris tabel yang disiapkan template (None = tidak terbatas)
    footer_row: int | None  # baris pertama rekap/tanda tangan di bawah tabel
    status_options: list[str] = field(default_factory=list)  # kosakata status template (dari validasi daftar)
    fields: list[TemplateField] = field(default_factory=list)

    @property
    def data_row(self) -> int:
        return self.header_row + 1


def _norm_label(value: object) -> str:
    return re.sub(r"[^a-z0-9/()]+", " ", str(value).lower().replace(":", " ")).strip()


def _header_row(ws: Worksheet) -> tuple[int, int]:
    """(baris, jumlah kolom dikenali) baris judul kolom terbaik di sheet ini."""
    best_row, best_score = 1, 0
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, HEADER_SCAN_ROWS)):
        score = len({canonical_header(c.value) for c in row if canonical_header(c.value)})
        if score > best_score:
            best_row, best_score = row[0].row, score
    return best_row, best_score


def _list_options(ws: Worksheet, column: int, row: int) -> list[str]:
    from openpyxl.utils import get_column_letter

    for r in range(row, row + 5):  # daftar status bisa dimulai beberapa baris di bawah judul kolom
        cell = f"{get_column_letter(column)}{r}"
        for dv in ws.data_validations.dataValidation:
            if dv.type == "list" and dv.formula1 and cell in dv.sqref:
                text = dv.formula1.strip()
                if text.startswith('"') and text.endswith('"'):
                    return [o.strip() for o in text[1:-1].split(",") if o.strip()]
    return []


def _merged_at(ws: Worksheet, row: int, col: int):
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return rng
    return None


def _fields(ws: Worksheet, header_row: int) -> list[TemplateField]:
    found: list[TemplateField] = []
    for row in ws.iter_rows(min_row=1, max_row=header_row - 1):
        for cell in row:
            if not isinstance(cell.value, str):
                continue
            key = _FIELD_INDEX.get(_norm_label(cell.value))
            if key is None:
                continue
            rng = _merged_at(ws, cell.row, cell.column)
            first = (rng.max_col if rng else cell.column) + 1
            col = first
            for c in range(first, first + 3):  # sel isian ": " bisa satu-dua kolom di kanan label
                v = ws.cell(cell.row, c).value
                if isinstance(v, str) and v.strip().startswith(":"):
                    col = c
                    break
                if v not in (None, ""):
                    break
            current = ws.cell(cell.row, col).value
            text = "" if current is None else str(current)
            if text.strip(" :"):
                continue  # sudah berisi (mis. "Version : 1.0" milik kepala dokumen) → jangan ditimpa
            found.append(TemplateField(label=cell.value.strip().rstrip(":").strip(), key=key, row=cell.row,
                                       value_col=col, prefix=": " if text.startswith(":") else ""))
    return found


_EXAMPLE_SHEET = re.compile(r"contoh|example|sample|sampel|petunjuk|guide", re.IGNORECASE)


def _filled_rows(ws: Worksheet, header_row: int, width: int) -> int:
    """Jumlah baris tabel yang sudah berisi data (≥2 sel terisi selain nomor urut)."""
    n = 0
    for r in range(header_row + 1, min(ws.max_row, header_row + 60) + 1):
        values = [ws.cell(r, c).value for c in range(2, width + 1)]
        if sum(1 for v in values if v not in (None, "")) >= 2:
            n += 1
    return n


def template_sheets(template: Path) -> list[dict]:
    """Sheet yang punya tabel test case: nama, baris judul, jumlah kolom dikenali, dan apakah sudah berisi data."""
    wb = load_workbook(template)
    out = []
    for ws in wb.worksheets:
        row, score = _header_row(ws)
        if score >= 2:
            width = sum(1 for c in ws[row] if c.value is not None)
            out.append({"name": ws.title, "header_row": row, "score": score,
                        "filled": _filled_rows(ws, row, max(width, 2)) > 0})
    return out


def read_template_info(template: Path, sheet: str | None = None) -> TemplateInfo:
    """Kenali tata letak template kantor: sheet, baris judul kolom, kapasitas tabel, rekap, status, isian kepala.

    Tanpa `sheet`, sheet bernama 'Template' / bertabel kosong diutamakan; sheet contoh yang sudah terisi paling akhir.
    """
    try:
        wb = load_workbook(template)
    except Exception as e:  # file rusak / bukan xlsx
        raise ValueError(f"Template Excel tidak bisa dibuka: {e}") from e
    best = None
    for ws in wb.worksheets:
        row, score = _header_row(ws)
        if score < 2:
            continue
        width = sum(1 for c in ws[row] if c.value is not None)
        rank = (ws.title == sheet,  # pilihan QA di Pengaturan
                "template" in ws.title.lower(),
                not _EXAMPLE_SHEET.search(ws.title),
                _filled_rows(ws, row, max(width, 2)) == 0,
                score)
        if best is None or rank > best[3]:
            best = (ws, row, score, rank)
    if best is None:
        raise ValueError("Template Excel harus punya baris judul kolom (mis. Skenario, Expected Result, Status)")
    ws, header_row, score, _ = best
    headers = [c.value for c in ws[header_row]]
    while headers and headers[-1] is None:
        headers.pop()
    columns = [canonical_header(h) for h in headers]
    width = len(headers)
    data_row = header_row + 1
    footer_row, last_prepared = None, None
    for r in range(data_row, ws.max_row + 1):
        texts = [ws.cell(r, c).value for c in range(1, width + 1)]
        if any(isinstance(v, str) and (v.startswith("=") or _FOOTER.search(v)) for v in texts):
            footer_row = r
            break
        if any(v not in (None, "") for v in texts):
            last_prepared = r
    status_col = columns.index("Status Final") + 1 if "Status Final" in columns else None
    capacity = None
    if footer_row is not None:
        # Baris yang disiapkan template: yang sudah bernomor/berisi, atau yang dicakup daftar pilihan status
        for dv in ws.data_validations.dataValidation:
            for rng in dv.sqref.ranges:
                if (status_col and rng.min_col <= status_col <= rng.max_col and rng.min_row <= data_row
                        and rng.max_row < footer_row):
                    last_prepared = max(last_prepared or 0, rng.max_row)
        capacity = (last_prepared - data_row + 1) if last_prepared else max(footer_row - data_row - 1, 0)
    options = _list_options(ws, status_col, data_row) if status_col else []
    return TemplateInfo(sheet=ws.title, header_row=header_row, columns=columns, headers=headers, capacity=capacity,
                        footer_row=footer_row, status_options=options, fields=_fields(ws, header_row))


_PASS = re.compile(r"pass|lulus|^ok$|sesuai|berhasil|success|^y(es)?$|^v$|✓|✔|√|☑", re.IGNORECASE)
_FAIL = re.compile(r"fail|gagal|tidak sesuai|bug|defect|error|^!$|not ok", re.IGNORECASE)
_PENDING = re.compile(r"pending|review|belum|hold|tunda|need|^\?$|in progress", re.IGNORECASE)
_BLOCKED = re.compile(r"block|skip|^x$|✗|✘|☒|tidak dapat|n/?a|cancel", re.IGNORECASE)


def _classify(value: str) -> str | None:
    text = value.strip()
    for status, pattern in (("Pass", _PASS), ("Fail", _FAIL), ("Perlu Review", _PENDING), ("Blocked", _BLOCKED)):
        if pattern.search(text):
            return status
    return None


def status_from_vocab(status: str | None, vocab: list[str]) -> str:
    """Status QA Agent → kosakata template kantor (mis. Pass → Passed, Fail → ✗)."""
    if not status:
        return ""
    if not vocab:
        return status
    by_class: dict[str, str] = {}
    for option in vocab:
        cls = _classify(option)
        if cls and cls not in by_class:
            by_class[cls] = option
    wanted = {"Pass": ["Pass"], "Fail": ["Fail"], "Perlu Review": ["Perlu Review", "Fail"],
              "Blocked": ["Blocked", "Perlu Review"], "Skipped": ["Blocked", "Perlu Review"]}.get(status, [status])
    for cls in wanted:
        if cls in by_class:
            return by_class[cls]
    return status


def status_to_standard(value: object) -> str | None:
    """Nilai status dari Excel (kosakata kantor atau standar) → status QA Agent."""
    text = _text(value)
    if not text:
        return None
    canonical = {s.lower(): s for s in STATUSES}
    return canonical.get(text.lower()) or _classify(text)


def _date_text(iso: str, long: bool) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}" if long else f"{d:%d-%m-%Y}"


def _shift_formula_ranges(text: str, old_last: int, new_last: int) -> str:
    """=COUNTIF(I13:I45,"Passed") → I13:I{new_last} bila rentang berakhir di baris terakhir tabel lama."""
    return re.sub(r"(\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?)(\d+)",
                  lambda m: f"{m.group(1)}{new_last if int(m.group(2)) == old_last else m.group(2)}", text)


def _grow_table(ws: Worksheet, info: TemplateInfo, needed: int) -> None:
    """Tabel template kurang panjang: geser rekap/tanda tangan ke bawah, perluas rumus, validasi, gaya baris."""
    from copy import copy

    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.cell_range import CellRange

    assert info.capacity is not None and info.footer_row is not None
    extra = needed - info.capacity
    old_last = info.data_row + info.capacity - 1
    new_last = old_last + extra
    last_col = get_column_letter(max(ws.max_column, len(info.columns)))
    footer_merges = [r for r in list(ws.merged_cells.ranges) if r.min_row >= info.footer_row]
    for rng in footer_merges:
        ws.merged_cells.remove(rng)
    heights = {r: ws.row_dimensions[r].height for r in range(info.footer_row, ws.max_row + 1)}
    ws.move_range(f"A{info.footer_row}:{last_col}{ws.max_row}", rows=extra, translate=False)
    for r, h in heights.items():
        ws.row_dimensions[r + extra].height = h
    for rng in footer_merges:
        ws.merge_cells(start_row=rng.min_row + extra, start_column=rng.min_col, end_row=rng.max_row + extra,
                       end_column=rng.max_col)
    for row in ws.iter_rows(min_row=info.footer_row + extra):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.value = _shift_formula_ranges(cell.value, old_last, new_last)
    # Baris baru meniru gaya & sel gabungan baris pertama tabel
    template_merges = [r for r in ws.merged_cells.ranges if r.min_row == r.max_row == info.data_row]
    for r in range(old_last + 1, new_last + 1):
        ws.row_dimensions[r].height = ws.row_dimensions[info.data_row].height
        for c in range(1, len(info.columns) + 1):
            src, dst = ws.cell(info.data_row, c), ws.cell(r, c)
            if src.has_style:
                dst._style = copy(src._style)
        for rng in template_merges:
            ws.merge_cells(start_row=r, start_column=rng.min_col, end_row=r, end_column=rng.max_col)
    for dv in ws.data_validations.dataValidation:
        ranges = []
        for rng in dv.sqref.ranges:
            cr = CellRange(rng.coord)
            if cr.max_row == old_last:
                cr = CellRange(min_col=cr.min_col, min_row=cr.min_row, max_col=cr.max_col, max_row=new_last)
            ranges.append(cr.coord)
        dv.sqref = " ".join(ranges)


def _fill_template(ws: Worksheet, info: TemplateInfo, meta: RunMeta, cases: list[QaTestCase], steps: list[StepRecord],
                   fields: dict[str, str], context: dict[str, str]) -> None:
    from openpyxl.utils import get_column_letter

    width = len(info.columns)
    if _filled_rows(ws, info.header_row, max(width, 2)):
        # Sheet contoh yang sudah berisi data: kosongkan isi tabel lama (gaya sel tetap)
        end = (info.footer_row - 1) if info.footer_row else ws.max_row
        for r in range(info.data_row, end + 1):
            for c in range(1, width + 1):
                cell = ws.cell(r, c)
                if isinstance(cell, MergedCell):  # bagian sel gabungan: nilainya ada di sel kiri atas
                    continue
                cell.value = None
                cell.hyperlink = None
    if info.capacity is not None and len(cases) > info.capacity:
        _grow_table(ws, info, len(cases))
    auto = {"date": _date_text(meta.started_at, long=True), "environment": "Production" if meta.environment == "production" else "Dev / UAT",
            "platform": "Android" if meta.target.startswith("android://") else "Web",
            "project": context.get("Project") or meta.target.split("://", 1)[-1].split("/", 1)[0]}
    for f in info.fields:
        value = fields.get(f.label)
        if value is None:
            value = auto.get(f.key, "")
        if value:
            ws.cell(f.row, f.value_col, f"{f.prefix}{value}" if f.prefix else value)
    columns = list(info.columns)
    if "TC ID" not in columns:  # kolom TC ID tersembunyi: review dari Excel kantor tetap bisa diimpor
        tc_col = ws.max_column + 1
        ws.cell(info.header_row, tc_col, "TC ID")
        ws.column_dimensions[get_column_letter(tc_col)].hidden = True
        columns += [None] * (tc_col - len(columns) - 1) + ["TC ID"]
    generic = "Status AI" not in columns
    date_short = _date_text(meta.started_at, long=False)
    for i, tc in enumerate(cases):
        row = info.data_row + i
        _fill_case_row(ws, row, columns, tc, steps, generic_status=generic, vocab=info.status_options,
                       extra={"No": i + 1, "Peran": context.get("Peran", ""), "Tanggal": date_short})


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
                      template: Path | None = None, fields: dict[str, str] | None = None,
                      context: dict[str, str] | None = None, sheet: str | None = None) -> None:
    """Laporan Excel. `template` = template Excel kantor (opsional, tata letak bebas) untuk sheet test case.

    `fields` = isian kepala template per label (mis. {"Developer": "Deni"}); `context` = nilai otomatis
    (Project = nama aplikasi, Peran = peran akun test).
    """
    if template is not None and cases:
        info = read_template_info(Path(template), sheet=sheet)
        wb = load_workbook(Path(template))
        ws = wb[info.sheet]
        for other in list(wb.worksheets):
            if other is not ws:
                wb.remove(other)  # sheet contoh / sheet lain dari template tidak ikut
        _fill_template(ws, info, meta, cases, steps, fields or {}, context or {})
        if not info.status_options:
            _status_validation_at(ws, info)
        _write_summary(wb.create_sheet("Ringkasan"), meta, cases)
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


def _case_table(wb: Workbook) -> tuple[Worksheet, int] | None:
    """Sheet & baris judul tabel test case: 'Test Cases' standar, atau sheet template kantor (ada kolom TC ID)."""
    if "Test Cases" in wb.sheetnames:
        return wb["Test Cases"], 1
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, HEADER_SCAN_ROWS)):
            names = {canonical_header(c.value) for c in row}
            if "TC ID" in names and len(names - {None}) >= 2:
                return ws, row[0].row
    return None


def _rows(path: Path) -> list[tuple[int, dict[str, object]]]:
    wb = load_workbook(path)
    table = _case_table(wb)
    if table is None:
        return []
    ws, header_row = table
    headers = [canonical_header(c.value) or c.value for c in ws[header_row]]  # template kantor → nama standar
    out = []
    for row_no, values in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
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
        status = (canonical.get(raw.lower()) or status_to_standard(raw)) if raw else None  # kosakata kantor juga
        if raw and status is None:
            raise ValueError(f"Baris {row_no}: Status Final '{raw}' tidak dikenal. Pilihan: {', '.join(STATUSES)}")
        review[tc_id] = {"status_final": status, "reviewer_note": _text(r.get("Catatan Reviewer"))}
    return review
