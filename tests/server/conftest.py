import time

import pytest

from qa_agent.llm.fake import FakeLLM
from qa_agent.server.events import EventHub
from qa_agent.server.runs import RunManager
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.brain import DemoBrain


def wait_for(predicate, timeout=90.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Kondisi tidak tercapai dalam batas waktu")


class Brains:
    """llm_factory yang bisa diganti di tengah test."""

    def __init__(self):
        self.make = lambda profile: FakeLLM(DemoBrain())

    def __call__(self, profile):
        return self.make(profile)


@pytest.fixture
def env(tmp_path):
    settings = ServerSettings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    store = Store(settings.db_path)
    secrets = MemorySecretStore()
    hub = EventHub()
    brains = Brains()
    manager = RunManager(store, secrets, hub, settings, llm_factory=brains)
    yield settings, store, secrets, hub, manager, brains
    manager.shutdown()
    store.close()


def seed_demo(store, secrets, demo):
    profile = store.create_profile(name="Demo", provider="openai_compatible", base_url="http://tidak-dipakai.test/v1",
                                   model="demo-brain", is_default=True)
    secrets.set(f"ai-profile:{profile.id}", "kunci-palsu")
    app = store.create_app(name="Demo HR", url=demo.url, allowed_domains=["127.0.0.1"])
    account = store.create_account(app_id=app.id, role="admin", username=DEMO_USER)
    secrets.set(f"account:{account.id}", DEMO_PASSWORD)
    return profile, app, account
