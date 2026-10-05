from qa_agent.report.html import status_class, write_report_html
from tests.report_fixtures import sample_run


def render(tmp_path, with_cases=True):
    store = sample_run(tmp_path / "run")
    cases = store.read_testcases() if with_cases else []
    steps = store.read_steps() if with_cases else []
    write_report_html(store.report_html, store.root, store.read_meta(), cases, steps, store.read_app_map())
    return store.report_html.read_text(encoding="utf-8")


def test_status_class():
    assert status_class("Perlu Review") == "s-perlu-review"
    assert status_class("Pass") == "s-pass"
    assert status_class(None) == "s-none"


def test_report_contains_cases_steps_and_images(tmp_path):
    html = render(tmp_path)
    assert html.startswith("<!doctype html>")
    assert 'id="TC-PEN-001"' in html and 'id="TC-PEN-003"' in html
    assert "Isi field &#39;Nama&#39; dengan &#39;Budi&#39;" in html
    assert "data:image/jpeg;base64," in html
    assert "HTTP 500 POST http://app.test/users" in html
    assert 'class="badge s-perlu-review"' in html


def test_findings_list_only_fail_and_review(tmp_path):
    html = render(tmp_path)
    findings = html.split('id="temuan"')[1].split("</section>")[0]
    assert "TC-PEN-002" in findings and "TC-PEN-003" in findings and "TC-PEN-001" not in findings


def test_user_text_is_escaped(tmp_path):
    html = render(tmp_path)
    assert "&lt;b&gt;tebal&lt;/b&gt;" in html and "<b>tebal</b>" not in html


def test_explore_only_report_shows_inventory(tmp_path):
    html = render(tmp_path, with_cases=False)
    assert "Inventaris Fitur" in html and "Daftar Pengguna" in html and 'id="temuan"' not in html
