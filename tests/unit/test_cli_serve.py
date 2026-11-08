import socket

from typer.testing import CliRunner

from qa_agent import cli
from qa_agent.cli import app, find_free_port


def test_find_free_port_skips_used_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        used = s.getsockname()[1]
        port = find_free_port(used)
        assert port != used and port > used


def test_find_free_port_returns_start_when_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert find_free_port(free) == free


def run_serve(monkeypatch, tmp_path, *args):
    calls = {}
    monkeypatch.setattr(cli, "find_free_port", lambda start, host="127.0.0.1": start + 1)
    monkeypatch.setattr("uvicorn.run", lambda app_, **kw: calls.update(kw, app=app_))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr(cli, "_open_browser_later", lambda url: opened.append(url))
    result = CliRunner().invoke(app, ["serve", "--data-dir", str(tmp_path / "data"), *args])
    return result, calls, opened


def test_serve_binds_localhost(monkeypatch, tmp_path):
    result, calls, opened = run_serve(monkeypatch, tmp_path, "--port", "8787", "--max-parallel", "3")
    assert result.exit_code == 0, result.output
    assert calls["host"] == "127.0.0.1" and calls["port"] == 8788
    assert opened == ["http://127.0.0.1:8788"]
    assert "http://127.0.0.1:8788" in result.output
    assert calls["app"].state.settings.max_parallel == 3
    assert (tmp_path / "data").is_dir()


def test_serve_no_browser(monkeypatch, tmp_path):
    result, _, opened = run_serve(monkeypatch, tmp_path, "--no-browser")
    assert result.exit_code == 0 and opened == []
