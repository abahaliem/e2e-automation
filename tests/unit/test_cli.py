import pytest
from typer.testing import CliRunner

from qa_agent import cli
from qa_agent.cli import app
from qa_agent.evidence import RunStore
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import RunMeta
from qa_agent.templates import CONFIG_TEMPLATE
from tests.report_fixtures import sample_run

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "qa-agent.yaml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(cli, "_check_browser", lambda: (True, ""))
    monkeypatch.setattr(cli, "_check_target", lambda url: (True, url))
    return tmp_path


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "s3cret!")
    monkeypatch.setenv("OFFICE_AI_KEY", "k")


def test_init_creates_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "qa-agent.yaml").exists() and (tmp_path / ".env.example").exists()
    assert "LEWATI" in runner.invoke(app, ["init"]).output


def test_check_invalid_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "qa-agent.yaml").write_text("target: {}", encoding="utf-8")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "[GAGAL] Config" in result.output


def test_check_reports_missing_secrets(project, monkeypatch):
    for name in ("QA_ADMIN_USER", "QA_ADMIN_PASS", "OFFICE_AI_KEY"):
        monkeypatch.setenv(name, "")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "[GAGAL] Kredensial akun" in result.output and "QA_ADMIN_USER" in result.output
    assert "[GAGAL] API key AI" in result.output


def test_check_all_ok_with_fake_llm(project, secrets, monkeypatch):
    monkeypatch.setattr(cli, "build_llm", lambda cfg: FakeLLM(["OK", "Merah"]))
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "[OK] Endpoint AI (teks)" in result.output and "[OK] Endpoint AI (gambar)" in result.output


def test_check_vision_wrong_answer_fails(project, secrets, monkeypatch):
    monkeypatch.setattr(cli, "build_llm", lambda cfg: FakeLLM(["OK", "saya tidak bisa melihat gambar"]))
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "[GAGAL] Endpoint AI (gambar)" in result.output


def test_report_rebuilds(project):
    store = sample_run(project / "runs" / "contoh")
    result = runner.invoke(app, ["report", "--run", str(store.root)])
    assert result.exit_code == 0, result.output
    assert store.report_xlsx.exists() and store.report_html.exists()


def test_report_rejects_non_run_folder(project):
    (project / "kosong").mkdir()
    result = runner.invoke(app, ["report", "--run", str(project / "kosong")])
    assert result.exit_code == 1 and "bukan folder run" in result.output


def test_deep_unknown_module_lists_modules(project, secrets):
    store = sample_run(project / "runs" / "explore")
    result = runner.invoke(app, ["deep", "--from", str(store.root), "--module", "Transaksi"])
    assert result.exit_code == 1 and "Pengguna" in result.output


def test_deep_rejects_pdf_prd(project, secrets):
    store = sample_run(project / "runs" / "explore")
    (project / "prd.pdf").write_bytes(b"%PDF")
    result = runner.invoke(app, ["deep", "--from", str(store.root), "--module", "Pengguna", "--prd", "prd.pdf"])
    assert result.exit_code == 1 and ".md atau .txt" in result.output


def test_run_rejects_explore_run(project, secrets):
    store = RunStore(project / "runs" / "x")
    store.write_meta(RunMeta(mode="explore", target="http://a", environment="dev", model="m", started_at="2026-10-05T10:00:00"))
    result = runner.invoke(app, ["run", "--run", str(store.root)])
    assert result.exit_code == 1 and "mode deep" in result.output


def test_invalid_env_option(project, secrets):
    result = runner.invoke(app, ["explore", "--env", "staging"])
    assert result.exit_code == 1 and "dev' atau 'production" in result.output
