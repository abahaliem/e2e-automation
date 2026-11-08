import pytest
from openpyxl import Workbook, load_workbook

from qa_agent.report.build import build_reports, import_review
from qa_agent.report.excel import TC_HEADERS, ReportLockedError
from tests.report_fixtures import sample_run


def test_build_then_review_roundtrip(tmp_path):
    store = sample_run(tmp_path / "run")
    xlsx, html = build_reports(store)
    assert xlsx.exists() and html.exists()

    wb = load_workbook(xlsx)
    ws = wb["Test Cases"]
    ws.cell(3, TC_HEADERS.index("Status Final") + 1).value = "Fail"
    ws.cell(3, TC_HEADERS.index("Catatan Reviewer") + 1).value = "Konfirmasi bug, email wajib valid"
    wb.save(xlsx)

    assert import_review(store) == 1
    assert store.read_review()["TC-PEN-002"]["status_final"] == "Fail"
    build_reports(store)

    ws = load_workbook(xlsx)["Test Cases"]
    assert ws.cell(3, TC_HEADERS.index("Status Final") + 1).value == "Fail"
    assert ws.cell(3, TC_HEADERS.index("Catatan Reviewer") + 1).value == "Konfirmasi bug, email wajib valid"
    text = html.read_text(encoding="utf-8")
    assert "Konfirmasi bug, email wajib valid" in text
    assert 'data-status="Fail"' in text and 'data-status="Perlu Review"' not in text


def test_build_keeps_reviewer_edits_not_yet_imported(tmp_path):
    # Review #7: akhir run/--resume menulis ulang report.xlsx; editan reviewer tidak boleh hilang
    store = sample_run(tmp_path / "run")
    xlsx, _ = build_reports(store)
    wb = load_workbook(xlsx)
    wb["Test Cases"].cell(2, TC_HEADERS.index("Status Final") + 1).value = "Fail"
    wb.save(xlsx)
    build_reports(store)
    assert load_workbook(xlsx)["Test Cases"].cell(2, TC_HEADERS.index("Status Final") + 1).value == "Fail"


def test_build_survives_invalid_review_cell(tmp_path):
    store = sample_run(tmp_path / "run")
    xlsx, _ = build_reports(store)
    wb = load_workbook(xlsx)
    wb["Test Cases"].cell(2, TC_HEADERS.index("Status Final") + 1).value = "Lulus"
    wb.save(xlsx)
    build_reports(store)  # tidak boleh crash di akhir run
    assert xlsx.exists()


def test_dashboard_review_not_overwritten_by_stale_excel(tmp_path, monkeypatch):
    # Review dari dashboard ditulis ke review.json saat report.xlsx terkunci (gagal ditulis ulang);
    # build berikutnya tidak boleh mengembalikan nilai lama dari Excel yang lebih tua.
    import os
    import time

    store = sample_run(tmp_path / "run")
    xlsx, _ = build_reports(store)
    old = time.time() - 60
    os.utime(xlsx, (old, old))
    store.write_review({"TC-PEN-002": {"status_final": "Fail", "reviewer_note": "dari dashboard", "severity": "Major"}})
    build_reports(store)
    assert store.read_review()["TC-PEN-002"]["status_final"] == "Fail"
    ws = load_workbook(xlsx)["Test Cases"]
    assert ws.cell(3, TC_HEADERS.index("Status Final") + 1).value == "Fail"


def test_build_without_excel_import(tmp_path):
    store = sample_run(tmp_path / "run")
    xlsx, _ = build_reports(store)
    wb = load_workbook(xlsx)
    wb["Test Cases"].cell(2, TC_HEADERS.index("Status Final") + 1).value = "Fail"
    wb.save(xlsx)
    build_reports(store, import_excel=False)
    assert load_workbook(xlsx)["Test Cases"].cell(2, TC_HEADERS.index("Status Final") + 1).value is None


def test_review_severity_applied(tmp_path):
    from qa_agent.report.build import apply_review

    store = sample_run(tmp_path / "run")
    cases = store.read_testcases()
    apply_review(cases, {"TC-PEN-002": {"status_final": "Fail", "reviewer_note": "", "severity": "Critical"}})
    assert cases[1].severity == "Critical" and cases[1].status_final == "Fail"


def test_import_review_without_report(tmp_path):
    store = sample_run(tmp_path / "run")
    assert import_review(store) == 0


def test_locked_report_propagates(tmp_path, monkeypatch):
    store = sample_run(tmp_path / "run")
    monkeypatch.setattr(Workbook, "save", lambda self, f: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(ReportLockedError):
        build_reports(store)
