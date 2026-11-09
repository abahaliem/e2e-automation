import re

from qa_agent.report.pdf_doc import render_pdf_html, summary_sentence
from tests.report_fixtures import sample_run


def html_for(tmp_path, **kw):
    store = sample_run(tmp_path / "run")
    return render_pdf_html(store, app_name="Web HR", **kw), store


def text(html):
    import html as html_lib

    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html)))


def test_header_and_meta(tmp_path):
    html, _ = html_for(tmp_path, run_id=12, company="PT Biznet")
    t = text(html)
    assert "Laporan Hasil Pengujian" in t
    assert "Web HR, modul Pengguna" in t
    assert "RUN-20261005-1430" in t
    assert "PT Biznet" in t
    for label, value in (("Aplikasi", "app.test"), ("Environment", "Dev / UAT"),
                         ("Tanggal pengujian", "5 Oktober 2026, 14.30"), ("Durasi", "12 menit"),
                         ("Model AI", "z-ai/glm-5.3-flash"), ("Status review", "0 dari 2 temuan sudah direview")):
        assert label in t and value in t


def test_summary_boxes_and_sentence(tmp_path):
    html, store = html_for(tmp_path)
    t = text(html)
    assert re.search(r"3 Test case 1 Pass 1 Fail 1 Perlu Review 0 Blocked", t)
    sentence = summary_sentence(store.read_testcases())
    assert sentence.startswith("Pass rate 33%.")
    assert "Nama dengan apostrof" in sentence


def test_findings_cards_with_repro_evidence_and_technical_proof(tmp_path):
    html, _ = html_for(tmp_path)
    t = text(html)
    assert "BUG-001" in t and "BUG-002" in t
    assert "Langkah reproduksi (TC-PEN-003)" in t
    assert "Isi field 'Nama' dengan 'Budi'" in t
    assert "HTTP 500 POST http://app.test/users" in t
    assert "Fail, Major" in t
    assert html.count("data:image/png;base64,") >= 2  # screenshot evidence tertanam (PDF tidak butuh file luar)


def test_case_table_and_footer(tmp_path):
    html, _ = html_for(tmp_path)
    t = text(html)
    assert "Daftar test case" in t
    assert "TC-PEN-001 Tambah pengguna valid Positif Pass" in t
    assert "Dibuat otomatis oleh QA Agent dan direview oleh QA. Dokumen internal." in t
    assert "<b>" not in html.split("Daftar test case")[1]  # judul di-escape


def test_reviewed_status_used(tmp_path):
    store = sample_run(tmp_path / "run")
    store.write_review({"TC-PEN-002": {"status_final": "Fail", "reviewer_note": "Dinaikkan menjadi Fail"}})
    t = text(render_pdf_html(store, app_name="Web HR"))
    assert "1 dari 2 temuan sudah direview" in t
    assert "Dinaikkan menjadi Fail" in t
    assert re.search(r"3 Test case 1 Pass 2 Fail 0 Perlu Review 0 Blocked", t)


def test_evidence_caption_describes_last_action(tmp_path):
    html, _ = html_for(tmp_path)
    assert "Setelah: Klik tombol 'Simpan'" in text(html)
