import signal
from datetime import datetime

import pytest

from qa_agent.config import Config, ConfigError
from qa_agent.evidence import RunStore
from qa_agent.llm.fake import FakeLLM
from qa_agent.runtime import StopFlag, build_runtime


def cfg():
    return Config.model_validate({
        "target": {"url": "https://app-dev.kantor.local"},
        "accounts": [{"role": "admin", "username_env": "RT_USER", "password_env": "RT_PASS"}],
        "llm": {"base_url": "http://ai.test/v1", "model": "fake", "api_key_env": "RT_KEY"},
    })


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RT_USER", "qa@kantor.local")
    monkeypatch.setenv("RT_PASS", "s3cret!")
    monkeypatch.setenv("RT_KEY", "k")


def test_build_runtime_dev(tmp_path, env):
    rt = build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="dev", llm=FakeLLM([]), now=datetime(2026, 10, 5, 14, 30))
    assert rt.data_prefix == "QA-AUTO-20261005-1430"
    assert rt.driver.request_filter is None
    assert rt.auth.state_path == tmp_path / ".qa-agent" / "auth" / "app-dev-kantor-local-admin.json"
    assert rt.masker.mask("s3cret!") == "••••••"
    assert rt.loop.relogin is None and rt.loop.max_steps == 25


def test_build_runtime_production_installs_request_filter(tmp_path, env):
    rt = build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="production", llm=FakeLLM([]))
    assert rt.driver.request_filter("POST", "https://app-dev.kantor.local/api/users") is True
    assert rt.driver.request_filter("POST", "https://app-dev.kantor.local/login") is False


def test_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_USER", "")
    with pytest.raises(ConfigError, match="RT_USER"):
        build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="dev", llm=FakeLLM([]))


def test_stop_flag_install():
    original = signal.getsignal(signal.SIGINT)
    try:
        flag = StopFlag()
        assert flag() is False
        flag.install()
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)  # simulasi Ctrl+C pertama
        assert flag() is True
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    finally:
        signal.signal(signal.SIGINT, original)
