"""Template Excel kantor dengan tata letak bebas (mis. SPN/GEN/P07/F01 UAT):
kepala dokumen, judul kolom tidak di baris 1, kolom gabungan, kosakata status sendiri, rekap di bawah tabel."""
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from qa_agent.models import QaTestCase, RunMeta
from qa_agent.report.excel import read_template_info, status_from_vocab, write_report_xlsx
from qa_agent.report.build import import_review_rows


def uat_template(path, capacity=8):
    """Meniru SPN_GEN_P07_F01: kepala, isian proyek, header baris 12, F:G digabung, rekap + tanda tangan."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Template"
    ws["D1"] = "User Acceptance Test (UAT)"
    ws["I1"], ws["J1"] = "No. Document", ": SPN/GEN/P07/F01"
    for row, (left, right) in enumerate([("Project Name", "UAT Date"), ("Developer", "Version (App/System)"),
                                         ("QA/Tester", "Segment"), ("User", "Platform")], start=7):
        ws.cell(row, 1, left)
        ws.cell(row, 3, ": ")
        ws.cell(row, 6, right)
        ws.cell(row, 8, ": ")
    headers = ["Item #", "User Role", "Modul / Menu", "Business Process", "Use Case / Scenario", "Expected Result",
               None, "Actual Result", "Status", "Comments"]
    for col, h in enumerate(headers, 1):
        ws.cell(12, col, h)
    ws.merge_cells("F12:G12")
    last = 12 + capacity
    for i, row in enumerate(range(13, last + 1), 1):
        ws.cell(row, 1, i)
        ws.merge_cells(f"F{row}:G{row}")
    dv = DataValidation(type="list", formula1='"Passed,Failed,Pending,Blocked"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"I13:I{last}")
    footer = last + 2
    ws.cell(footer, 1, "REKAP HASIL UAT")
    ws.cell(footer, 7, "KESIMPULAN")
    for k, status in enumerate(["Passed", "Failed", "Pending", "Blocked"], start=1):
        ws.cell(footer + k, 1, status)
        ws.cell(footer + k, 5, f'=COUNTIF(I13:I{last},"{status}")')
    ws.cell(footer + 5, 1, "TOTAL TEST CASE")
    ws.cell(footer + 5, 5, f"=COUNTA(I13:I{last})")
    ws.merge_cells(start_row=footer + 1, start_column=7, end_row=footer + 1, end_column=8)
    wb.create_sheet("Contoh")["A1"] = "contoh pengisian"
    wb.save(path)
    return path


def symbol_template(path):
    """Meniru sheet 'QM - Hendi': isian di kolom A/B, header baris 6, status ✓ / ! / X."""
    wb = Workbook()
    ws = wb.active
    ws.title = "QM"
    ws["A1"], ws["B1"], ws["D1"] = "Project : ", "", "Segment :"
    ws["A3"], ws["A4"] = "QA/Tester:", "Platform:"
    for col, h in enumerate(["Item #", "Module", "Test Case Description", "Steps to Execute", "Expected Result",
                             "Actual Result", "Status", "Screenshot (URL)", "Priority", "Test Date", "Notes"], 1):
        ws.cell(6, col, h)
    dv = DataValidation(type="list", formula1='"✓,!,X"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("G8:G100")
    ws["L8"] = "! = Actual Result berbeda dengan Expected"
    ws["L9"] = "✓ = Actual Result sudah sesuai dengan Expected"
    ws["L10"] = "X = Module belum bisa / belum berhasil dijalankan"
    wb.save(path)
    return path


def meta():
    return RunMeta(mode="deep", target="android://com.biznet.wfm.dev", environment="dev", model="m",
                   started_at="2026-11-10T09:00:00", finished_at="2026-11-10T09:30:00", status="completed",
                   module="Autentikasi")


def case(n, status, **kw):
    return QaTestCase(id=f"TC-AUT-{n:03d}", module="Autentikasi", title=f"Skenario {n}", steps=["Buka", "Tap"],
                      expected="Berhasil", actual="Sesuai", status_ai=status, **kw)


def test_reads_uat_layout(tmp_path):
    info = read_template_info(uat_template(tmp_path / "uat.xlsx"))
    assert info.sheet == "Template" and info.header_row == 12
    assert info.columns[:6] == ["No", "Peran", "Modul", "Skenario", "Langkah", "Expected Result"]
    assert info.columns[7:10] == ["Actual Result", "Status Final", "Catatan Reviewer"]
    assert info.capacity == 8 and info.footer_row == 22
    assert info.status_options == ["Passed", "Failed", "Pending", "Blocked"]
    assert [f.label for f in info.fields] == ["Project Name", "UAT Date", "Developer", "Version (App/System)",
                                              "QA/Tester", "Segment", "User", "Platform"]


def test_status_vocabulary_mapping():
    vocab = ["Passed", "Failed", "Pending", "Blocked"]
    assert status_from_vocab("Pass", vocab) == "Passed"
    assert status_from_vocab("Fail", vocab) == "Failed"
    assert status_from_vocab("Perlu Review", vocab) == "Pending"
    assert status_from_vocab("Blocked", vocab) == "Blocked"
    assert status_from_vocab("Skipped", vocab) == "Blocked"
    symbols = ["✓", "!", "X"]
    assert [status_from_vocab(s, symbols) for s in ("Pass", "Fail", "Perlu Review", "Blocked")] == ["✓", "!", "!", "X"]


def test_fills_uat_template_header_and_rows(tmp_path):
    out = tmp_path / "report.xlsx"
    cases = [case(1, "Pass"), case(2, "Fail", reviewer_note="Harusnya ditolak"), case(3, "Perlu Review")]
    write_report_xlsx(out, meta(), cases, [], None, template=uat_template(tmp_path / "uat.xlsx"),
                      fields={"Project Name": "WFM Biznet", "QA/Tester": "Abdul", "Developer": ""},
                      context={"Peran": "user"})
    wb = load_workbook(out)
    assert wb.sheetnames[0] == "Template"  # format kantor jadi sheet pertama
    ws = wb["Template"]
    assert ws["C7"].value == ": WFM Biznet" and ws["C9"].value == ": Abdul"
    assert ws["H7"].value == ": 10 November 2026"  # tanggal otomatis
    assert ws["H10"].value == ": Android"  # platform otomatis
    assert [ws.cell(13, c).value for c in (1, 2, 3, 4)] == [1, "user", "Autentikasi", "Skenario 1"]
    assert ws["E13"].value == "1. Buka\n2. Tap" and ws["F13"].value == "Berhasil"
    assert [ws[f"I{r}"].value for r in (13, 14, 15)] == ["Passed", "Failed", "Pending"]
    assert ws["J14"].value == "Harusnya ditolak"
    assert ws["A16"].value == 4 and ws["I16"].value is None  # baris template sisa tetap rapi
    assert ws["E23"].value == '=COUNTIF(I13:I20,"Passed")'  # rekap tidak berubah
    assert "Contoh" not in wb.sheetnames


def test_grows_table_and_moves_footer_when_cases_exceed_capacity(tmp_path):
    out = tmp_path / "report.xlsx"
    cases = [case(n, "Pass") for n in range(1, 11)]  # 10 test case, template hanya 8 baris
    write_report_xlsx(out, meta(), cases, [], None, template=uat_template(tmp_path / "uat.xlsx"))
    ws = load_workbook(out)["Template"]
    assert ws["A22"].value == 10 and ws["I22"].value == "Passed"
    assert ws["A24"].value == "REKAP HASIL UAT"  # rekap bergeser 2 baris
    assert ws["E25"].value == '=COUNTIF(I13:I22,"Passed")' and ws["E29"].value == "=COUNTA(I13:I22)"
    assert "F22:G22" in {str(r) for r in ws.merged_cells.ranges}  # gaya baris (F:G digabung) ikut
    assert "G25:H25" in {str(r) for r in ws.merged_cells.ranges}
    assert any("I13:I22" in str(dv.sqref) for dv in ws.data_validations.dataValidation)


def test_symbol_status_template(tmp_path):
    out = tmp_path / "report.xlsx"
    write_report_xlsx(out, meta(), [case(1, "Pass"), case(2, "Fail"), case(3, "Blocked")], [], None,
                      template=symbol_template(tmp_path / "qm.xlsx"))
    ws = load_workbook(out)["QM"]
    assert ws["B1"].value == "WFM" or ws["B1"].value  # isian Project terisi nama aplikasi/target
    assert [ws[f"G{r}"].value for r in (7, 8, 9)] == ["✓", "!", "X"]  # data mulai tepat di bawah header
    assert ws["J7"].value == "10-11-2026" or ws["J7"].value  # Test Date terisi


def test_review_round_trip_from_office_vocabulary(tmp_path):
    out = tmp_path / "report.xlsx"
    write_report_xlsx(out, meta(), [case(1, "Pass"), case(2, "Perlu Review")], [], None,
                      template=uat_template(tmp_path / "uat.xlsx"))
    wb = load_workbook(out)
    ws = wb["Template"]
    ws["I14"] = "Failed"  # reviewer memutuskan di Excel kantor
    ws["J14"] = "Bug: pesan error tidak muncul"
    wb.save(out)
    rows = {r["TC ID"]: r for r in import_review_rows(out)}
    assert rows["TC-AUT-002"]["Status Final"] == "Fail" and rows["TC-AUT-002"]["Catatan Reviewer"].startswith("Bug")
