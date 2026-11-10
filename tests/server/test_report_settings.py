import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store
from tests.report_fixtures import sample_run


def test_store_settings_roundtrip(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert store.get_setting("report.company") is None
    store.set_setting("report.company", "PT Biznet")
    assert store.get_setting("report.company") == "PT Biznet"
    store.set_setting("report.company", None)
    assert store.get_setting("report.company") is None


def template_bytes(headers):
    wb = Workbook()
    wb.active.append(headers)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def ctx(tmp_path):
    settings = ServerSettings(data_dir=tmp_path / "data")
    app = create_app(settings, secrets=MemorySecretStore())
    with TestClient(app) as client:
        yield client, settings


def test_report_settings_api(ctx):
    client, settings = ctx
    assert client.get("/api/settings/report").json() == {"company_name": "", "excel_template": None, "logo": None}
    assert client.patch("/api/settings/report", json={"company_name": "PT Biznet"}).json()["company_name"] == "PT Biznet"
    r = client.post("/api/settings/report/template?filename=template-kantor.xlsx",
                    content=template_bytes(["No. TC", "Skenario Pengujian", "Hasil yang Diharapkan", "Kolom Lain"]))
    assert r.status_code == 200, r.text
    tpl = r.json()["excel_template"]
    assert tpl["name"] == "template-kantor.xlsx"
    assert tpl["columns"] == [
        {"header": "No. TC", "maps_to": "TC ID"},
        {"header": "Skenario Pengujian", "maps_to": "Skenario"},
        {"header": "Hasil yang Diharapkan", "maps_to": "Expected Result"},
        {"header": "Kolom Lain", "maps_to": None},
    ]
    bad = client.post("/api/settings/report/template?filename=x.xlsx", content=template_bytes(["A", "B"]))
    assert bad.status_code == 422 and "judul kolom" in bad.json()["detail"]
    assert client.post("/api/settings/report/template?filename=x.csv", content=b"a,b").status_code == 422
    assert client.delete("/api/settings/report/template").status_code == 204
    assert client.get("/api/settings/report").json()["excel_template"] is None


def test_download_uses_template_and_pdf_design(ctx):
    client, settings = ctx
    app = client.post("/api/apps", json={"name": "Web HR", "url": "http://app.test"}).json()
    rs = sample_run(settings.runs_dir / "r1")
    client.post("/api/import-runs", json={"folder": str(rs.root), "app_id": app["id"]})
    run_id = client.get("/api/runs").json()[0]["id"]
    client.post("/api/settings/report/template?filename=t.xlsx",
                content=template_bytes(["No. TC", "Skenario Pengujian", "Status"]))
    client.patch("/api/settings/report", json={"company_name": "PT Biznet"})
    rs.report_xlsx.unlink(missing_ok=True)
    r = client.get(f"/api/runs/{run_id}/download/xlsx")
    ws = load_workbook(io.BytesIO(r.content))["Sheet"]
    assert [c.value for c in ws[1]] == ["No. TC", "Skenario Pengujian", "Status"]
    # review dari dashboard membangun ulang Excel dengan template yang sama
    client.patch(f"/api/runs/{run_id}/cases/TC-PEN-002", json={"status_final": "Fail"})
    ws = load_workbook(rs.report_xlsx)["Sheet"]
    assert ws.cell(3, 3).value == "Fail"


@pytest.mark.browser
def test_pdf_download_uses_mockup_08_document(ctx):
    client, settings = ctx
    app = client.post("/api/apps", json={"name": "Web HR", "url": "http://app.test"}).json()
    rs = sample_run(settings.runs_dir / "r2")
    client.post("/api/import-runs", json={"folder": str(rs.root), "app_id": app["id"]})
    run_id = client.get("/api/runs").json()[0]["id"]
    r = client.get(f"/api/runs/{run_id}/download/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    html = (rs.root / "report_pdf.html").read_text(encoding="utf-8")
    assert "Laporan Hasil Pengujian" in html and "Web HR, modul Pengguna" in html


def png_bytes(size=(1200, 400), color=(37, 96, 232, 255)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_company_logo_upload_preview_delete(ctx):
    from PIL import Image

    client, settings = ctx
    r = client.post("/api/settings/report/logo?filename=logo-biznet.png", content=png_bytes())
    assert r.status_code == 200, r.text
    logo = r.json()["logo"]
    assert logo["name"] == "logo-biznet.png" and logo["url"].startswith("/api/settings/report/logo")
    img = client.get(logo["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    shrunk = Image.open(io.BytesIO(img.content))
    assert shrunk.width <= 800 and shrunk.height <= 300  # diperkecil untuk kepala dokumen
    # bukan gambar / format tidak didukung / terlalu besar → ditolak
    assert client.post("/api/settings/report/logo?filename=logo.png", content=b"bukan gambar").status_code == 422
    r = client.post("/api/settings/report/logo?filename=logo.svg", content=b"<svg/>")
    assert r.status_code == 422 and "PNG, JPG, atau WEBP" in r.json()["detail"]
    assert client.post("/api/settings/report/logo?filename=big.png", content=b"x" * (2 * 1024 * 1024 + 1)).status_code == 422
    assert client.delete("/api/settings/report/logo").status_code == 204
    assert client.get("/api/settings/report").json()["logo"] is None
    assert client.get("/api/settings/report/logo").status_code == 404


def test_pdf_html_shows_company_logo(tmp_path):
    from qa_agent.report.pdf_doc import render_pdf_html

    rs = sample_run(tmp_path / "r")
    html = render_pdf_html(rs, app_name="WFM", company="PT Biznet", logo="data:image/png;base64,AAAA")
    assert '<img class="company-logo" src="data:image/png;base64,AAAA"' in html and "PT Biznet" in html
    plain = render_pdf_html(rs, app_name="WFM", company="PT Biznet")
    assert '<img class="company-logo"' not in plain and "QA Agent" in plain