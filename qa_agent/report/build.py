from __future__ import annotations

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


def import_review(store: RunStore) -> int:
    if not store.report_xlsx.exists():
        return 0
    review = read_review(store.report_xlsx)
    store.write_review(review)
    return sum(1 for r in review.values() if r["status_final"] or r["reviewer_note"])


def build_reports(store: RunStore) -> tuple[Path, Path]:
    meta = store.read_meta()
    cases = store.read_testcases()
    apply_review(cases, store.read_review())
    steps = store.read_steps()
    app_map = store.read_app_map()
    write_report_xlsx(store.report_xlsx, meta, cases, steps, app_map)
    write_report_html(store.report_html, store.root, meta, cases, steps, app_map)
    return store.report_xlsx, store.report_html
