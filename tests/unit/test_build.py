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


def test_import_review_without_report(tmp_path):
    store = sample_run(tmp_path / "run")
    assert import_review(store) == 0


def test_locked_report_propagates(tmp_path, monkeypatch):
    store = sample_run(tmp_path / "run")
    monkeypatch.setattr(Workbook, "save", lambda self, f: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(ReportLockedError):
        build_reports(store)
