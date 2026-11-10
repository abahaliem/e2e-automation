import pytest
from openpyxl import Workbook, load_workbook

from qa_agent.report.excel import (
    PLAN_HEADERS,
    TC_HEADERS,
    ReportLockedError,
    import_cases_xlsx,
    read_review,
    write_cases_xlsx,
    write_report_xlsx,
)
from tests.report_fixtures import sample_run


def build(tmp_path):
    store = sample_run(tmp_path / "run")
    write_report_xlsx(store.report_xlsx, store.read_meta(), store.read_testcases(), store.read_steps(), store.read_app_map())
    return store, load_workbook(store.report_xlsx)


def col(ws, header):
    headers = [c.value for c in ws[1]]
    return headers.index(header) + 1


def test_sheets_and_headers(tmp_path):
    _, wb = build(tmp_path)
    assert wb.sheetnames == ["Ringkasan", "Test Cases", "Temuan", "Inventaris Fitur"]
    # mockup 09: 12 kolom, header biru aksen dengan teks putih tebal
    assert TC_HEADERS == ["TC ID", "Modul", "Skenario", "Tipe", "Prioritas", "Langkah", "Expected Result",
                          "Actual Result", "Status AI", "Status Final", "Catatan Reviewer", "Evidence"]
    ws = wb["Test Cases"]
    assert [c.value for c in ws[1]] == TC_HEADERS
    assert ws.freeze_panes == "A2"
    assert ws.cell(1, 1).fill.fgColor.rgb.endswith("2560E8")
    assert ws.cell(1, 1).font.bold and ws.cell(1, 1).font.color.rgb.endswith("FFFFFF")
    assert ws.cell(2, col(ws, "Tipe")).value == "Positif"


def test_test_case_rows_status_colors_and_links(tmp_path):
    _, wb = build(tmp_path)
    ws = wb["Test Cases"]
    assert ws.cell(2, 1).value == "TC-PEN-001"
    assert ws.cell(2, col(ws, "Langkah")).value == "1. Buka form\n2. Isi data\n3. Klik Simpan"
    status = ws.cell(2, col(ws, "Status AI"))
    assert status.value == "Pass" and status.fill.fgColor.rgb.endswith("C6EFCE")
    assert ws.cell(4, col(ws, "Status AI")).fill.fgColor.rgb.endswith("FFC7CE")
    evidence = ws.cell(2, col(ws, "Evidence"))
    assert evidence.hyperlink.target == "screenshots/TC-PEN-001_step-03.png"

    assert any("Pass,Fail,Perlu Review,Blocked,Skipped" in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)


def test_findings_only_fail_and_review(tmp_path):
    _, wb = build(tmp_path)
    ws = wb["Temuan"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert [r[1] for r in rows] == ["TC-PEN-002", "TC-PEN-003"]
    assert rows[0][0] == "BUG-001"
    assert "1. Isi field 'Nama' dengan 'Budi'" in rows[1][5]
    assert "HTTP 500 POST http://app.test/users" in rows[1][8]


def test_summary_counts(tmp_path):
    _, wb = build(tmp_path)
    values = {row[0]: row[1:] for row in wb["Ringkasan"].iter_rows(values_only=True) if row[0]}
    assert values["Target"][0] == "http://app.test"
    assert values["Durasi"][0] == "12 menit 30 detik"
    assert values["Pass"][:2] == (1, 1)
    assert values["Fail"][:2] == (1, 1)
    assert values["Pass rate"][0] == "33%"


def test_inventory_sheet(tmp_path):
    _, wb = build(tmp_path)
    row = next(wb["Inventaris Fitur"].iter_rows(min_row=2, values_only=True))
    assert row[:4] == ("Pengguna", "Daftar Pengguna", "http://app.test/users", "Melihat daftar pengguna")
    assert "Kata kunci (text)" in row[4]


def test_explore_only_report(tmp_path):
    store = sample_run(tmp_path / "run")
    write_report_xlsx(store.report_xlsx, store.read_meta(), [], [], store.read_app_map())
    assert load_workbook(store.report_xlsx).sheetnames == ["Ringkasan", "Inventaris Fitur"]


def test_read_review_roundtrip(tmp_path):
    store, wb = build(tmp_path)
    ws = wb["Test Cases"]
    ws.cell(3, col(ws, "Status Final")).value = "fail"
    ws.cell(3, col(ws, "Catatan Reviewer")).value = "Bug valid, lapor ke dev"
    wb.save(store.report_xlsx)
    review = read_review(store.report_xlsx)
    assert review["TC-PEN-002"] == {"status_final": "Fail", "reviewer_note": "Bug valid, lapor ke dev"}
    assert review["TC-PEN-001"] == {"status_final": None, "reviewer_note": ""}


def test_read_review_rejects_unknown_status(tmp_path):
    store, wb = build(tmp_path)
    ws = wb["Test Cases"]
    ws.cell(2, col(ws, "Status Final")).value = "Lulus"
    wb.save(store.report_xlsx)
    with pytest.raises(ValueError, match="Baris 2.*Lulus"):
        read_review(store.report_xlsx)


def test_cases_xlsx_roundtrip_and_new_row(tmp_path):
    store = sample_run(tmp_path / "run")
    write_cases_xlsx(store.cases_xlsx, store.read_testcases())
    wb = load_workbook(store.cases_xlsx)
    ws = wb["Test Cases"]
    assert [c.value for c in ws[1]] == PLAN_HEADERS
    ws.append([None, "Pengguna", "Daftar Pengguna", "Cari pengguna", "Navigasi", "Low", "", "", "1. Ketik nama\n2) Tekan cari",
               "Hasil muncul", "Inferensi AI", "http://app.test/users"])
    ws.delete_rows(2)  # reviewer menghapus TC-PEN-001
    wb.save(store.cases_xlsx)
    cases = import_cases_xlsx(store.cases_xlsx)
    assert [c.id for c in cases] == ["TC-PEN-002", "TC-PEN-003", "TC-PEN-004"]
    assert cases[2].steps == ["Ketik nama", "Tekan cari"] and cases[2].type == "navigasi"
    assert all(c.status_ai is None for c in cases)


def test_import_cases_reports_row_number(tmp_path):
    store = sample_run(tmp_path / "run")
    write_cases_xlsx(store.cases_xlsx, store.read_testcases())
    wb = load_workbook(store.cases_xlsx)
    wb["Test Cases"].cell(3, PLAN_HEADERS.index("Tipe") + 1).value = "acak"
    wb.save(store.cases_xlsx)
    with pytest.raises(ValueError, match="Baris 3"):
        import_cases_xlsx(store.cases_xlsx)


def test_control_characters_and_formula_like_text_are_written_safely(tmp_path):
    # Review #8: karakter kontrol (ANSI) dan teks diawali "=" tidak boleh merusak laporan
    store = sample_run(tmp_path / "run")
    cases = store.read_testcases()
    cases[0].title = '=HYPERLINK("http://evil")'
    cases[1].actual = "Console: [31mError[0m"
    write_report_xlsx(store.report_xlsx, store.read_meta(), cases, store.read_steps(), None)
    ws = load_workbook(store.report_xlsx)["Test Cases"]
    title = ws.cell(2, col(ws, "Skenario"))
    assert title.value == '=HYPERLINK("http://evil")' and title.data_type == "s"
    assert ws.cell(3, col(ws, "Actual Result")).value == "Console: [31mError[0m"


def test_locked_workbook_raises_friendly_error(tmp_path, monkeypatch):
    store = sample_run(tmp_path / "run")

    def locked(self, filename):
        raise PermissionError(13, "Permission denied", str(filename))

    monkeypatch.setattr(Workbook, "save", locked)
    with pytest.raises(ReportLockedError, match="Tutup"):
        write_report_xlsx(store.report_xlsx, store.read_meta(), store.read_testcases(), store.read_steps(), None)


def test_precondition_and_test_data_kept_in_steps_cell(tmp_path):
    from qa_agent.models import QaTestCase

    store = sample_run(tmp_path / "run")
    cases = store.read_testcases()
    cases[0] = cases[0].model_copy(update={"precondition": "Login sebagai admin", "test_data": "Nama: QA-AUTO Valid"})
    write_report_xlsx(store.report_xlsx, store.read_meta(), cases, store.read_steps(), store.read_app_map())
    ws = load_workbook(store.report_xlsx)["Test Cases"]
    text = ws.cell(2, col(ws, "Langkah")).value
    assert text.startswith("Pre-condition: Login sebagai admin\n1. Buka form")
    assert text.endswith("Test data: Nama: QA-AUTO Valid")


def office_template(path, headers, sheet="Daftar Uji"):
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="00B050")
        cell.font = Font(bold=True, name="Arial")
    ws.column_dimensions["B"].width = 55
    wb.save(path)
    return path


def test_office_template_controls_test_case_columns(tmp_path):
    template = office_template(tmp_path / "template.xlsx",
                               ["No. TC", "Skenario Pengujian", "Hasil yang Diharapkan", "Hasil Aktual", "Status",
                                "Keterangan", "Kolom Kantor Lain"])
    store = sample_run(tmp_path / "run")
    write_report_xlsx(store.report_xlsx, store.read_meta(), store.read_testcases(), store.read_steps(),
                      store.read_app_map(), template=template)
    wb = load_workbook(store.report_xlsx)
    assert "Test Cases" in wb.sheetnames
    ws = wb["Test Cases"]
    assert [c.value for c in ws[1]] == ["No. TC", "Skenario Pengujian", "Hasil yang Diharapkan", "Hasil Aktual",
                                        "Status", "Keterangan", "Kolom Kantor Lain"]
    assert ws.cell(1, 1).fill.fgColor.rgb.endswith("00B050")  # gaya header template dipertahankan
    assert ws.column_dimensions["B"].width == 55
    assert ws.cell(2, 1).value == "TC-PEN-001" and ws.cell(2, 2).value == "Tambah pengguna valid"
    assert ws.cell(4, 4).value == "Server error 500" and ws.cell(4, 5).value == "Fail"
    assert ws.cell(2, 7).value is None
    # review dari Excel versi template tetap terbaca
    ws.cell(3, 5).value = "Fail"
    ws.cell(3, 6).value = "Dinaikkan"
    wb.save(store.report_xlsx)
    review = read_review(store.report_xlsx)
    assert review["TC-PEN-002"] == {"status_final": "Fail", "reviewer_note": "Dinaikkan"}


def test_header_aliases():
    from qa_agent.report.excel import canonical_header

    assert canonical_header("No. TC") == "TC ID"
    assert canonical_header("  ID Test Case ") == "TC ID"
    assert canonical_header("Expected") == "Expected Result"
    assert canonical_header("Status Akhir") == "Status Final"
    assert canonical_header("Kolom aneh") is None