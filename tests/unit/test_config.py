import pytest

from qa_agent.config import ConfigError, load_config

YAML = """
target:
  url: https://app-dev.kantor.local/
accounts:
  - role: admin
    username_env: QA_ADMIN_USER
    password_env: QA_ADMIN_PASS
llm:
  base_url: http://192.168.151.121/v1
  model: z-ai/glm-5.3-flash
  api_key_env: OFFICE_AI_KEY
"""


def write(tmp_path, text=YAML):
    path = tmp_path / "qa-agent.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults(tmp_path):
    cfg = load_config(write(tmp_path), env_file=tmp_path / "tidak-ada.env")
    assert cfg.target.url == "https://app-dev.kantor.local"
    assert cfg.environment == "dev"
    assert cfg.llm.provider == "openai_compatible"
    assert cfg.llm.vision is True
    assert cfg.llm.timeout_seconds == 60
    assert cfg.limits.max_steps_per_tc == 25
    assert cfg.limits.deep_max_tcs == 15
    assert cfg.limits.explore_max_screens == 60
    assert cfg.limits.explore_max_depth == 5
    assert cfg.limits.explore_max_minutes == 45
    assert cfg.browser.headless is False
    assert cfg.browser.size == (1366, 768)
    assert cfg.domains() == ["app-dev.kantor.local"]


def test_credentials_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "s3cret!")
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    creds = cfg.credentials()
    assert (creds.role, creds.username, creds.password) == ("admin", "qa@kantor.local", "s3cret!")
    assert cfg.credentials("admin").username == "qa@kantor.local"


def test_unknown_role(tmp_path, monkeypatch):
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    with pytest.raises(ConfigError, match="operator"):
        cfg.credentials("operator")


def test_missing_env_var_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "")
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    with pytest.raises(ConfigError, match="QA_ADMIN_PASS"):
        cfg.credentials()


def test_env_file_is_loaded(tmp_path, monkeypatch):
    # setenv lalu delenv: monkeypatch mencatat "tidak ada" sehingga variabel dibersihkan setelah test
    monkeypatch.setenv("DOTENV_TEST_KEY", "x")
    monkeypatch.delenv("DOTENV_TEST_KEY")
    (tmp_path / ".env").write_text("DOTENV_TEST_KEY=abc123\n", encoding="utf-8")
    cfg = load_config(write(tmp_path, YAML.replace("OFFICE_AI_KEY", "DOTENV_TEST_KEY")))
    assert cfg.api_key() == "abc123"


def test_invalid_url(tmp_path):
    with pytest.raises(ConfigError, match="target.url"):
        load_config(write(tmp_path, YAML.replace("https://app-dev.kantor.local/", "app-dev")), env_file=tmp_path / "x.env")


def test_invalid_viewport(tmp_path):
    text = YAML + "browser:\n  viewport: besar\n"
    with pytest.raises(ConfigError, match="browser.viewport"):
        load_config(write(tmp_path, text), env_file=tmp_path / "x.env")


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="qa-agent init"):
        load_config(tmp_path / "tidak-ada.yaml")


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="YAML"):
        load_config(write(tmp_path, "target: [tidak ditutup"), env_file=tmp_path / "x.env")
