import re

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect

from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER

pytestmark = pytest.mark.browser


def test_dashboard_end_to_end(dashboard, demo, page, tmp_path):
    base = dashboard.url
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # 1. Profil AI
    page.goto(f"{base}/settings")
    page.get_by_label("Nama profil").fill("AI demo")
    page.get_by_label("Base URL endpoint").fill("http://tidak-dipakai.test/v1")
    page.get_by_label("API key").fill("sk-demo-123456")
    page.get_by_label("Model").fill("demo-brain")
    page.get_by_role("button", name="Simpan").click()
    expect(page.get_by_text("sk-••••3456")).to_be_visible()
    assert "sk-demo-123456" not in page.content()

    # 2. Aplikasi demo + akun test
    page.goto(f"{base}/apps")
    page.get_by_role("button", name="Tambah aplikasi").click()
    page.get_by_label("Nama aplikasi").fill("Demo HR")
    page.get_by_label("URL aplikasi").fill(demo.url)
    page.get_by_label("Domain yang boleh dibuka").fill("127.0.0.1")
    page.get_by_role("button", name="Simpan aplikasi").click()
    page.get_by_label("Peran").fill("admin")
    page.get_by_label("Username / email").fill(DEMO_USER)
    page.get_by_label("Password").fill(DEMO_PASSWORD)
    page.get_by_role("button", name="Tambah akun").click()
    expect(page.get_by_text("Password tersimpan", exact=True)).to_be_visible()

    # 3. Run seluruh aplikasi + layar live + intervensi
    page.get_by_role("link", name="Jalankan pengujian").click()
    expect(page.get_by_label("URL aplikasi")).to_have_value(demo.url)
    page.get_by_role("button", name="Mulai run").click()
    expect(page).to_have_url(re.compile(r"/runs/\d+$"))
    live = page.get_by_alt_text("Tampilan langsung browser yang sedang diuji agent")
    expect(live).to_have_attribute("src", re.compile(r"^blob:"), timeout=60_000)
    page.get_by_role("button", name="Jeda", exact=True).click()
    expect(page.get_by_text("Dijeda", exact=True)).to_be_visible()
    page.get_by_label("Arahkan agent").fill("Pastikan menu Laporan ikut dipetakan")
    page.get_by_role("button", name="Kirim").click()
    expect(page.get_by_label("Arahkan agent")).to_have_value("")
    page.get_by_role("button", name="Lanjutkan").click()
    expect(page.get_by_text("Run selesai.")).to_be_visible(timeout=120_000)

    # 4. Run satu modul Pengguna
    page.goto(f"{base}/apps")
    page.get_by_role("link", name="Jalankan pengujian").click()
    mode = page.get_by_role("radio", name=re.compile("Satu modul"))
    expect(mode).to_be_enabled()
    mode.click()
    page.get_by_label("Modul").select_option("Pengguna")
    page.get_by_role("button", name="Mulai run").click()
    expect(page).to_have_url(re.compile(r"/runs/\d+$"))
    expect(page.get_by_text("Run selesai.")).to_be_visible(timeout=180_000)
    page.get_by_role("link", name="Lihat hasil").click()

    # 5. Hasil: 3 test case, review TC-PEN-002, unduh Excel
    table = page.get_by_role("table")
    for title in ("Tambah pengguna dengan data valid", "Validasi format email", "Nama dengan apostrof"):
        expect(table.get_by_text(title)).to_be_visible()
    table.get_by_text("Validasi format email").click()
    panel = page.get_by_role("region", name="Detail test case")
    expect(panel.get_by_text("TC-PEN-002")).to_be_visible()
    panel.get_by_label("Status final").select_option("Fail")
    panel.get_by_role("button", name="Simpan review").click()
    expect(panel.get_by_text("Review disimpan dan laporan diperbarui.")).to_be_visible()

    with page.expect_download() as info:
        page.get_by_role("link", name="Excel").click()
    target = tmp_path / "hasil.xlsx"
    info.value.save_as(target)
    ws = load_workbook(target)["Test Cases"]
    header = [c.value for c in ws[1]]
    rows = {r[header.index("TC ID")]: r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    assert rows["TC-PEN-002"][header.index("Status Final")] == "Fail"

    # 6. Dashboard menampilkan angka dan temuan
    page.goto(base)
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_text("Validasi format email").first).to_be_visible()
    assert errors == []
