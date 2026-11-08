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


def test_default_data_dir():
    assert default_data_dir() == Path.home() / "QA Agent"
