"""Bukti error: foto tepat saat error muncul disimpan ke folder run dan dipakai di Temuan."""
from openpyxl import load_workbook

from qa_agent.evidence import RunStore
from qa_agent.models import QaTestCase, RunMeta, Signal, StepRecord
from qa_agent.report.excel import write_report_xlsx
from qa_agent.report.humanize import error_evidence, signal_text

PNG = b"\x89PNG\r\n\x1a\nfake"


def test_attach_evidence_saves_png_and_links_signal(tmp_path):
    store = RunStore(tmp_path / "run")
    toast = Signal(kind="ui_error", message="Pesan muncul sesaat lalu hilang: Gagal simpan", at="2026-11-11T09:15:02")
    js = Signal(kind="console_error", message="x is undefined")
    store.attach_evidence("TC-1_step-03", [toast, js], {toast.message: PNG})
    assert toast.screenshot == "screenshots/TC-1_step-03_error-1.png"
    assert (tmp_path / "run" / toast.screenshot).read_bytes() == PNG
    assert js.screenshot is None
    store.attach_evidence("TC-1_step-03", [toast], {toast.message: b"lain"})  # tidak ditimpa
    assert (tmp_path / "run" / toast.screenshot).read_bytes() == PNG


def test_android_crash_label_not_javascript():
    assert signal_text(Signal(kind="page_error", message="Aplikasi tertutup sendiri (crash)")) == "Aplikasi tertutup sendiri (crash)"


def test_finding_links_error_evidence(tmp_path):
    sig = Signal(kind="ui_error", message="Gagal memuat order", screenshot="screenshots/TC-1_step-02_error-1.png")
    steps = [StepRecord(tc_id="TC-1", step_no=1, timestamp="t", action="click", screenshot="screenshots/a.png"),
             StepRecord(tc_id="TC-1", step_no=2, timestamp="t", action="click", signals=[sig], screenshot="screenshots/b.png")]
    assert error_evidence(steps) is sig
    tc = QaTestCase(id="TC-1", module="WO", title="Buka order", expected="Daftar order tampil", status_ai="Fail",
                    actual="Muncul pesan gagal")
    meta = RunMeta(mode="deep", target="https://app.test", environment="dev", model="m", started_at="2026-11-11T09:00:00",
                   finished_at="2026-11-11T09:10:00", status="completed")
    path = tmp_path / "r.xlsx"
    write_report_xlsx(path, meta, [tc], steps, None)
    ws = load_workbook(path)["Temuan"]
    row = [c for c in ws[2]]
    assert any(c.value and "Pesan error di layar: Gagal memuat order" in str(c.value) for c in row)
    link = row[-1]
    assert link.value == "Bukti error" and link.hyperlink.target == "screenshots/TC-1_step-02_error-1.png"
