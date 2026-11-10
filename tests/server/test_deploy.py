import pytest
from typer.testing import CliRunner

from qa_agent.cli import app as cli
from qa_agent.server.auth import verify_password
from qa_agent.server.secrets import FileSecretStore, SecretStoreUnavailable, generate_master_key, secret_store_for
from qa_agent.server.store import Store


def test_file_secret_store_encrypts(tmp_path):
    key = generate_master_key()
    path = tmp_path / "secrets.json.enc"
    s = FileSecretStore(path, key)
    s.set("profile:1", "sk-rahasia-123")
    assert s.get("profile:1") == "sk-rahasia-123"
    assert b"sk-rahasia" not in path.read_bytes()
    assert FileSecretStore(path, key).get("profile:1") == "sk-rahasia-123"  # tersimpan
    s.delete("profile:1")
    s.delete("tidak-ada")
    assert s.get("profile:1") is None


def test_file_secret_store_wrong_or_missing_key(tmp_path):
    path = tmp_path / "s.enc"
    FileSecretStore(path, generate_master_key()).set("a", "b")
    with pytest.raises(SecretStoreUnavailable):
        FileSecretStore(path, generate_master_key()).get("a")
    with pytest.raises(SecretStoreUnavailable):
        FileSecretStore(path, "")


def test_secret_store_for(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_AGENT_MASTER_KEY", generate_master_key())
    assert isinstance(secret_store_for("file", tmp_path), FileSecretStore)
    monkeypatch.delenv("QA_AGENT_MASTER_KEY")
    with pytest.raises(SecretStoreUnavailable):
        secret_store_for("file", tmp_path)


def test_cli_user_add_list_passwd(tmp_path):
    runner = CliRunner()
    data = str(tmp_path)
    r = runner.invoke(cli, ["user", "add", "admin", "--role", "admin", "--data-dir", data],
                      input="admin-pass-1\nadmin-pass-1\n")
    assert r.exit_code == 0, r.output
    store = Store(tmp_path / "qa-agent.db")
    u = store.get_user_by_name("admin")
    assert u.role == "admin" and verify_password("admin-pass-1", u.password_hash)
    store.close()
    r = runner.invoke(cli, ["user", "add", "x", "--data-dir", data], input="pendek\npendek\n")
    assert r.exit_code != 0 and "minimal 8" in r.output
    r = runner.invoke(cli, ["user", "list", "--data-dir", data])
    assert "admin" in r.output and "Admin" in r.output
    r = runner.invoke(cli, ["user", "passwd", "admin", "--data-dir", data], input="baru-pass-12\nbaru-pass-12\n")
    assert r.exit_code == 0, r.output
    store = Store(tmp_path / "qa-agent.db")
    assert verify_password("baru-pass-12", store.get_user_by_name("admin").password_hash)
    store.close()


def test_cli_secret_key():
    r = CliRunner().invoke(cli, ["secret-key"])
    assert r.exit_code == 0
    key = r.output.strip().splitlines()[-1]
    FileSecretStore.__init__  # noqa: B018 - kunci harus valid untuk Fernet
    from cryptography.fernet import Fernet

    Fernet(key.encode())


def test_serve_refuses_public_host_without_auth(tmp_path):
    r = CliRunner().invoke(cli, ["serve", "--host", "0.0.0.0", "--data-dir", str(tmp_path), "--no-browser"])
    assert r.exit_code != 0 and "--auth" in r.output
