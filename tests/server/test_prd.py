from qa_agent.server.events import EventHub
from qa_agent.server.runs import RunManager, RunRequest
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store


def test_prd_from_explore_reused_by_deep(tmp_path):
    settings = ServerSettings(data_dir=tmp_path)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")
    app = store.create_app(name="X", url="http://app.test")
    explore = store.create_run(app_id=app.id, mode="explore", environment="dev", folder=str(tmp_path / "e"),
                               options={"prd_text": "# PRD Pengguna\nEmail wajib valid"})
    store.update_run(explore.id, status="completed")
    from qa_agent.evidence import RunStore
    from qa_agent.models import AppMap, ScreenInfo

    RunStore(tmp_path / "e").write_app_map(AppMap(target="http://app.test", screens=[
        ScreenInfo(fingerprint="f", url="http://app.test/users", module="Pengguna", page_name="Daftar")]))
    manager = RunManager(store, MemorySecretStore(), EventHub(), settings)
    manager._enqueue = lambda run_id: None  # jangan jalankan worker
    deep = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna"))
    assert deep.options["prd_text"].startswith("# PRD Pengguna")
    own = manager.submit(RunRequest(app_id=app.id, mode="deep", module="Pengguna", prd_text="PRD baru"))
    assert own.options["prd_text"] == "PRD baru"
    explore2 = manager.submit(RunRequest(app_id=app.id, mode="explore", prd_text="PRD explore"))
    assert explore2.options["prd_text"] == "PRD explore"
