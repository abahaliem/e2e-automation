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


def test_run_prompts_include_active_skills(env, demo):
    from qa_agent.server.skillbank import skills_dir, text_path
    from tests.integration.brain import DemoBrain

    settings, store, secrets, _, manager, brains = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    plan_only = store.create_skill(name="Standar TC", filename="s.md", pages=1, chars=20, stages=["plan"])
    exec_only = store.create_skill(name="Checklist", filename="c.md", pages=1, chars=20, stages=["execute"])
    other_app = store.create_skill(name="Aplikasi lain", filename="o.md", pages=1, chars=20, stages=["plan"], app_ids=[999])
    skills_dir(settings).mkdir(parents=True, exist_ok=True)
    text_path(settings, plan_only.id).write_text("ATURAN-PLAN-123", encoding="utf-8")
    text_path(settings, exec_only.id).write_text("ATURAN-EXEC-456", encoding="utf-8")
    text_path(settings, other_app.id).write_text("TIDAK-BOLEH-MUNCUL", encoding="utf-8")
    systems: list[str] = []

    def factory(profile_row):
        brain = DemoBrain()

        def respond(system, messages):
            systems.append(system)
            return brain(system, messages)

        return FakeLLM(respond)

    brains.make = factory
    explore(manager, store, profile, app, account)
    run = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", profile_id=profile.id,
                                    account_id=account.id, environment="dev"))
    finished(store, run.id)
    plan = [s for s in systems if s.startswith("MODE: PLAN")][0]
    execute = [s for s in systems if s.startswith("MODE: EXECUTE")][-1]
    assert "QA Engineer profesional" in plan and "ATURAN-PLAN-123" in plan and "ATURAN-EXEC-456" not in plan
    assert "ATURAN-EXEC-456" in execute and "ATURAN-PLAN-123" not in execute
    assert not any("TIDAK-BOLEH-MUNCUL" in s for s in systems)


def test_review_first_then_edit_and_run(env, demo):
    """Susun test case → berhenti 'Menunggu review' → QA edit/hapus → jalankan (Lanjutkan) → hanya yang tersisa."""
    _, store, secrets, _, manager, _ = env
    manager.start()
    profile, app, account = seed_demo(store, secrets, demo)
    explore(manager, store, profile, app, account)
    run = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", profile_id=profile.id,
                                    account_id=account.id, environment="dev", review_first=True))
    paused = finished(store, run.id, ("paused",))
    from qa_agent.server.runs import REVIEW_NOTE

    assert paused.note == REVIEW_NOTE
    planned = manager.plan(run.id)
    assert len(planned) == 3 and all(c.status_ai is None for c in planned)
    first = planned[0].model_copy(update={"title": "Judul diedit QA"})
    manager.update_plan(run.id, [first, planned[2]])
    assert [c.tc_id for c in store.list_cases(run.id)] == [planned[0].id, planned[1].id]  # nomor diurutkan ulang
    manager.resume(run.id)
    done = finished(store, run.id)
    cases = store.list_cases(run.id)
    assert len(cases) == 2 and cases[0].title == "Judul diedit QA" and all(c.status_ai for c in cases)

    # Regresi: ulang dengan test case yang sama (tanpa AI menyusun ulang)
    again = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", profile_id=profile.id,
                                      account_id=account.id, environment="dev", reuse_cases_from=done.id))
    finished(store, again.id)
    assert [c.title for c in store.list_cases(again.id)] == [c.title for c in cases]