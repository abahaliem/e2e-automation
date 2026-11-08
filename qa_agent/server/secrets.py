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


def mask_secret(value: str | None) -> str:
    """`sk-abcdef123456` -> `sk-••••3456`; nilai pendek -> `••••`."""
    if not value:
        return ""
    if len(value) <= 4:
        return MASK
    prefix = value[:3] if value.startswith("sk-") else ""
    return f"{prefix}{MASK}{value[-4:]}"
