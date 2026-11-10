"""Penyimpanan rahasia (API key, password akun test).

Satu antarmuka `SecretStore`; backend default memakai keyring (Windows
Credential Manager). Tidak ada fallback ke teks biasa: bila keyring tidak
tersedia, operasi melempar `SecretStoreUnavailable`.
"""
from __future__ import annotations

import threading
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

MASK = "••••"


class SecretStoreUnavailable(Exception):
    """Backend penyimpanan rahasia tidak bisa dipakai."""


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class MemorySecretStore:
    """Untuk test: rahasia hanya di memori proses."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


class KeyringSecretStore:
    def __init__(self, service: str = "qa-agent") -> None:
        self.service = service

    def get(self, key: str) -> str | None:
        try:
            return keyring.get_password(self.service, key)
        except KeyringError as e:
            raise SecretStoreUnavailable(str(e)) from e

    def set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self.service, key, value)
        except KeyringError as e:
            raise SecretStoreUnavailable(str(e)) from e

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self.service, key)
        except PasswordDeleteError:
            return
        except KeyringError as e:
            raise SecretStoreUnavailable(str(e)) from e


MASTER_KEY_ENV = "QA_AGENT_MASTER_KEY"
BACKEND_ENV = "QA_AGENT_SECRET_BACKEND"


def generate_master_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


class FileSecretStore:
    """Backend server (Linux/Docker): satu file terenkripsi Fernet dengan kunci induk dari variabel lingkungan."""

    def __init__(self, path, master_key: str) -> None:
        from pathlib import Path

        from cryptography.fernet import Fernet

        if not master_key:
            raise SecretStoreUnavailable(f"Kunci induk belum diatur. Buat dengan 'qa-agent secret-key' lalu isi {MASTER_KEY_ENV}")
        try:
            self._fernet = Fernet(master_key.encode())
        except (ValueError, TypeError) as e:
            raise SecretStoreUnavailable(f"{MASTER_KEY_ENV} tidak valid") from e
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        import json

        from cryptography.fernet import InvalidToken

        if not self.path.is_file():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self.path.read_bytes()).decode("utf-8"))
        except InvalidToken as e:
            raise SecretStoreUnavailable(f"File rahasia tidak bisa dibuka: {MASTER_KEY_ENV} salah") from e

    def _save(self, data: dict[str, str]) -> None:
        import json
        import os

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(self._fernet.encrypt(json.dumps(data).encode("utf-8")))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._load().get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(key, None) is not None:
                self._save(data)


def secret_store_for(backend: str, data_dir) -> SecretStore:
    """`keyring` (default, Windows Credential Manager) atau `file` (server)."""
    import os
    from pathlib import Path

    if backend == "file":
        return FileSecretStore(Path(data_dir) / "secrets.json.enc", os.environ.get(MASTER_KEY_ENV, ""))
    if backend == "keyring":
        return KeyringSecretStore()
    raise SecretStoreUnavailable(f"Backend rahasia tidak dikenal: {backend}")


def mask_secret(value: str | None) -> str:
    """`sk-abcdef123456` -> `sk-••••3456`; nilai pendek -> `••••`."""
    if not value:
        return ""
    if len(value) <= 4:
        return MASK
    prefix = value[:3] if value.startswith("sk-") else ""
    return f"{prefix}{MASK}{value[-4:]}"
