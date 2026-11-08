import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail

from qa_agent.server.secrets import (
    KeyringSecretStore,
    MemorySecretStore,
    SecretStoreUnavailable,
    mask_secret,
)


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        from keyring.errors import PasswordDeleteError

        if (service, username) not in self.data:
            raise PasswordDeleteError("tidak ada")
        del self.data[(service, username)]


@pytest.fixture
def restore_keyring():
    old = keyring.get_keyring()
    yield
    keyring.set_keyring(old)


def test_memory_roundtrip():
    s = MemorySecretStore()
    assert s.get("ai-profile:1") is None
    s.set("ai-profile:1", "sk-123")
    assert s.get("ai-profile:1") == "sk-123"
    s.delete("ai-profile:1")
    assert s.get("ai-profile:1") is None
    s.delete("ai-profile:1")  # hapus kunci yang tidak ada tidak error


def test_mask_secret():
    assert mask_secret("sk-abcdef123456") == "sk-••••3456"
    assert mask_secret("abcd") == "••••"
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("abcdefgh") == "••••efgh"


def test_keyring_roundtrip(restore_keyring):
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    s = KeyringSecretStore()
    s.set("account:7", "rahasia")
    assert s.get("account:7") == "rahasia"
    assert backend.data[("qa-agent", "account:7")] == "rahasia"
    s.delete("account:7")
    assert s.get("account:7") is None
    s.delete("account:7")


def test_keyring_unavailable_no_fallback(restore_keyring):
    keyring.set_keyring(fail.Keyring())
    s = KeyringSecretStore()
    with pytest.raises(SecretStoreUnavailable):
        s.set("account:1", "x")
    with pytest.raises(SecretStoreUnavailable):
        s.get("account:1")
