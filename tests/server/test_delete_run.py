"""Hapus run dari Riwayat run: data di database dan folder evidence ikut terhapus."""
import pytest
from fastapi.testclient import TestClient

from qa_agent.evidence import RunStore
from qa_agent.models import QaTestCase
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings


@pytest.fixture
def ctx(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        a = store.create_app(name="Web", platform="web", url="http://x.test", allowed_domains=[], login_endpoints=[])

        def make_run(status="completed"):
            rs = RunStore.create(app.state.settings.runs_dir, "deep", "pengguna")
            cases = [QaTestCase(id="TC-PEN-001", module="Pengguna", title="t", expected="e", status_ai="Pass")]
            rs.write_testcases(cases)
            row = store.create_run(app_id=a.id, mode="deep", module="Pengguna", environment="dev", folder=str(rs.root))
            store.upsert_cases(row.id, cases)
            store.update_run(row.id, status=status)
            return row.id, rs.root

        yield client, app, store, make_run


def test_delete_finished_run_removes_rows_and_folder(ctx):
    client, _, store, make_run = ctx
    run_id, folder = make_run()
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert store.get_run(run_id) is None and store.list_cases(run_id) == []
    assert not folder.exists()
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.delete(f"/api/runs/{run_id}").status_code == 404


def test_cannot_delete_running_run(ctx):
    client, app, _, make_run = ctx
    run_id, folder = make_run(status="running")
    app.state.manager.is_active = lambda rid: rid == run_id
    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 409 and "Hentikan" in r.json()["detail"]
    assert folder.exists()


def test_folder_outside_runs_dir_is_not_deleted(ctx, tmp_path):
    client, _, store, make_run = ctx
    run_id, _ = make_run()
    outside = tmp_path / "penting"
    outside.mkdir()
    store.update_run(run_id, folder=str(outside))
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert outside.exists()  # hanya folder di dalam folder runs yang dihapus


def test_delete_app_with_runs_removes_everything(ctx):
    """Aplikasi yang punya riwayat run bisa dihapus beserta run, evidence, akun, alur, data uji, persiapan."""
    from qa_agent.evidence import RunStore
    from qa_agent.server.testdata import hook_secret_key

    client, _, store, make_run = ctx
    app_id = store.list_apps()[0].id
    run_id, folder = make_run()
    acc = store.create_account(app_id=app_id, role="user", username="18111337")
    client.app.state.secrets.set(f"account:{acc.id}", "rahasia")
    store.create_flow(app_id=app_id, name="Alur WO", steps="1. buka")
    store.add_test_data(app_id, "wo_id", ["1"])
    hook = store.create_hook(app_id=app_id, name="Buat WO", url="https://dev.test/wo")
    client.app.state.secrets.set(hook_secret_key(hook.id), "{}")
    r = client.delete(f"/api/apps/{app_id}")
    assert r.status_code == 409 and "riwayat run" in r.json()["detail"]  # tanpa konfirmasi: ditolak
    assert client.delete(f"/api/apps/{app_id}?with_runs=true").status_code == 204
    assert store.get_app(app_id) is None and store.get_run(run_id) is None and not folder.exists()
    assert store.list_flows(app_id) == [] and store.list_test_data(app_id) == [] and store.list_hooks(app_id) == []
    assert client.app.state.secrets.get(f"account:{acc.id}") is None
    assert client.app.state.secrets.get(hook_secret_key(hook.id)) is None


def test_delete_app_refused_while_run_active(ctx):
    client, app, store, make_run = ctx
    app_id = store.list_apps()[0].id
    run_id, folder = make_run(status="running")
    app.state.manager.is_active = lambda rid: rid == run_id
    r = client.delete(f"/api/apps/{app_id}?with_runs=true")
    assert r.status_code == 409 and "berjalan" in r.json()["detail"] and folder.exists()