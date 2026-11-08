import threading

import pytest

from qa_agent.llm.fake import FakeLLM
from qa_agent.server.runs import RunRequest
from tests.demo_app.app import DEMO_PASSWORD
from tests.server.conftest import seed_demo, wait_for

pytestmark = pytest.mark.browser


def finished(store, run_id, statuses=("completed",)):
    return wait_for(lambda: store.get_run(run_id).status in statuses and store.get_run(run_id))


def explore(manager, store, profile, app, account):
    run = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                    environment="dev"))
    return finished(store, run.id)


def test_explore_then_deep(env, demo, monkeypatch):
    monkeypatch.delenv("DEMO_PASS", raising=False)
    settings, store, secrets, hub, manager, _ = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    events: list[dict] = []
    original = hub.publish
    hub.publish = lambda run_id, e: events.append(e) or original(run_id, e)

    run = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                    environment="dev"))
    assert run.status == "queued"
    done = finished(store, run.id)
    assert (settings.runs_dir / done.folder.split("\\")[-1].split("/")[-1]).exists()
    assert any(e["type"] == "screen.added" for e in events)
    assert any(e["type"] == "run.status" and e["status"] == "running" for e in events)
    assert hub.snapshot(run.id)["status"] == "completed"
    assert manager.modules(app.id) == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]

    deep = manager.submit(RunRequest(app_id=app.id, mode="deep", module="pengguna", profile_id=profile.id,
                                     account_id=account.id, environment="dev"))
    deep_done = finished(store, deep.id)
    cases = store.list_cases(deep.id)
    assert [c.status_ai for c in cases] == ["Pass", "Perlu Review", "Fail"]
    assert deep_done.counts == {"Pass": 1, "Perlu Review": 1, "Fail": 1}
    assert deep_done.module == "Pengguna"
    assert any(e["type"] == "tc.finished" for e in events)
    from pathlib import Path
    folder = Path(deep_done.folder)
    assert (folder / "report.xlsx").exists() and (folder / "report.html").exists()
    assert DEMO_PASSWORD not in (folder / "steps.jsonl").read_text(encoding="utf-8")


def test_deep_without_explore_rejected(env, demo):
    _, store, secrets, _, manager, _ = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    with pytest.raises(ValueError, match="Jalankan Seluruh aplikasi dulu"):
        manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", profile_id=profile.id,
                                  account_id=account.id, environment="dev"))


def test_same_app_runs_sequentially(env, demo):
    _, store, secrets, _, manager, _ = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    gate = threading.Event()
    inner = FakeLLM.__call__ if hasattr(FakeLLM, "__call__") else None  # noqa: F841

    from tests.integration.brain import DemoBrain

    def slow(profile_row):
        brain = DemoBrain()

        def respond(system, messages):
            gate.wait(30)
            return brain(system, messages)

        return FakeLLM(respond)

    env[5].make = slow
    r1 = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                   environment="dev"))
    r2 = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                   environment="dev"))
    wait_for(lambda: store.get_run(r1.id).status == "running")
    assert store.get_run(r2.id).status == "queued"
    gate.set()
    finished(store, r1.id)
    finished(store, r2.id)


def test_llm_error_pauses_then_resume(env, demo):
    _, store, secrets, _, manager, brains = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    brains.make = lambda p: FakeLLM([])  # langsung kehabisan jawaban → LLMError
    run = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                    environment="dev"))
    paused = finished(store, run.id, ("paused",))
    assert "AI" in paused.note
    from tests.integration.brain import DemoBrain
    brains.make = lambda p: FakeLLM(DemoBrain())
    resumed = manager.resume(run.id)
    assert resumed.status == "queued"
    finished(store, run.id)


def test_start_marks_unfinished_interrupted(env):
    _, store, _, _, manager, _ = env
    app = store.create_app(name="X", url="http://app.test")
    run = store.create_run(app_id=app.id, mode="explore", environment="dev", folder="x", status="running")
    manager.start()
    assert store.get_run(run.id).status == "interrupted"


def test_credentials_come_from_secret_store(env, demo, monkeypatch):
    for name in ("DEMO_USER", "DEMO_PASS", "DEMO_AI_KEY"):
        monkeypatch.delenv(name, raising=False)
    _, store, secrets, _, manager, brains = env
    seen = {}

    def factory(profile_row):
        seen["profile"] = profile_row.id
        from tests.integration.brain import DemoBrain
        return FakeLLM(DemoBrain())

    brains.make = factory
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    done = explore(manager, store, profile, app, account)
    assert done.status == "completed" and seen["profile"] == profile.id
    # tanpa password di SecretStore, login gagal → run dijeda dengan pesan
    secrets.delete(f"account:{account.id}")
    run = manager.submit(RunRequest(app_id=app.id, mode="explore", profile_id=profile.id, account_id=account.id,
                                    environment="dev"))
    paused = finished(store, run.id, ("paused",))
    assert "Password akun" in paused.note


def test_stop_command_interrupts(env, demo):
    _, store, secrets, _, manager, brains = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    explore(manager, store, profile, app, account)
    run = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", profile_id=profile.id,
                                    account_id=account.id, environment="dev"))
    wait_for(lambda: store.get_run(run.id).status == "running")
    manager.command(run.id, "pause")
    manager.command(run.id, "stop")
    stopped = finished(store, run.id, ("interrupted",))
    assert "QA" in stopped.note
