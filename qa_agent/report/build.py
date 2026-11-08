from __future__ import annotations

import zipfile
from pathlib import Path

from qa_agent.evidence import RunStore
from qa_agent.models import QaTestCase
from qa_agent.report.excel import read_review, write_report_xlsx
from qa_agent.report.html import write_report_html


def apply_review(cases: list[QaTestCase], review: dict) -> None:
    for tc in cases:
        entry = review.get(tc.id)
        if entry:
            tc.status_final = entry.get("status_final")
            tc.reviewer_note = entry.get("reviewer_note", "")
            if entry.get("severity"):
                tc.severity = entry["severity"]


def import_review(store: RunStore) -> int:
    if not store.report_xlsx.exists():
        return 0
    review = read_review(store.report_xlsx)
    if review:  # laporan explore tidak punya sheet Test Cases; jangan timpa review.json dengan kosong
        existing = store.read_review()
        for tc_id, entry in review.items():  # severity hanya diatur dari dashboard; pertahankan
            if existing.get(tc_id, {}).get("severity"):
                entry["severity"] = existing[tc_id]["severity"]
        store.write_review(review)
    return sum(1 for r in review.values() if r["status_final"] or r["reviewer_note"])


def excel_is_newer(store: RunStore) -> bool:
    """Editan di report.xlsx hanya diimpor bila file Excel lebih baru dari review.json.

    Review dari dashboard yang tersimpan saat Excel terkunci tidak boleh ditimpa nilai lama dari Excel.
    """
    if not store.report_xlsx.exists():
        return False
    if not store.review_path.exists():
        return True
    return store.report_xlsx.stat().st_mtime >= store.review_path.stat().st_mtime


def build_reports(store: RunStore, *, import_excel: bool = True) -> tuple[Path, Path]:
    # Editan reviewer di report.xlsx yang belum diimpor tidak boleh hilang saat laporan ditulis ulang.
    if import_excel and excel_is_newer(store):
        try:
            import_review(store)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            pass  # isi review tidak valid/tidak terbaca: pakai review.json terakhir; `qa-agent report` menampilkan error-nya
    meta = store.read_meta()
    cases = store.read_testcases()
    apply_review(cases, store.read_review())
    steps = store.read_steps()
    app_map = store.read_app_map()
    write_report_xlsx(store.report_xlsx, meta, cases, steps, app_map)
    write_report_html(store.report_html, store.root, meta, cases, steps, app_map)
    return store.report_xlsx, store.report_html
