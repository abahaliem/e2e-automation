from pathlib import Path

from qa_agent.server.settings import ServerSettings, default_data_dir


def test_settings_paths(tmp_path: Path):
    data_dir = tmp_path / "data"
    s = ServerSettings(data_dir=data_dir)
    assert s.db_path == data_dir / "qa-agent.db"
    assert s.runs_dir == data_dir / "runs"
    assert s.auth_dir == data_dir / "auth"

    s.ensure_dirs()
    assert s.runs_dir.is_dir()
    assert s.auth_dir.is_dir()
    assert data_dir.is_dir()


def test_default_host_port(tmp_path: Path):
    s = ServerSettings(data_dir=tmp_path)
    assert s.host == "127.0.0.1"
    assert s.port == 8787
    assert s.max_parallel == 2


def test_browsers_dir_used_when_present(tmp_path, monkeypatch):
    from qa_agent.server.settings import configure_playwright_browsers

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    s = ServerSettings(data_dir=tmp_path)
    assert s.browsers_dir == tmp_path / "browsers"
    assert configure_playwright_browsers(s) is None  # folder belum ada: biarkan default Playwright
    (s.browsers_dir / "chromium_headless_shell-1243").mkdir(parents=True)
    assert configure_playwright_browsers(s) == str(s.browsers_dir)
    import os

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(s.browsers_dir)


def test_browsers_env_from_user_is_respected(tmp_path, monkeypatch):
    from qa_agent.server.settings import configure_playwright_browsers

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "D:/lain")
    s = ServerSettings(data_dir=tmp_path)
    (s.browsers_dir / "chromium-1").mkdir(parents=True)
    assert configure_playwright_browsers(s) == "D:/lain"


def test_default_data_dir():
    assert default_data_dir() == Path.home() / "QA Agent"
