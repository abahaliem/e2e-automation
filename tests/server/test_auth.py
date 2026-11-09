import time

import pytest
from fastapi.testclient import TestClient

from qa_agent.server.app import create_app
from qa_agent.server.auth import hash_password, verify_password
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store

H = {"X-QA-Agent": "1"}


def test_password_hashing():
    h = hash_password("rahasia-123")
    assert h.startswith("pbkdf2_sha256$") and "rahasia-123" not in h
    assert verify_password("rahasia-123", h)
    assert not verify_password("salah", h)
    assert hash_password("rahasia-123") != h  # salt berbeda


def test_store_users_and_sessions(tmp_path):
    store = Store(tmp_path / "db")
    u = store.create_user(username="admin", password_hash=hash_password("x"), role="admin")
    assert store.get_user_by_name("ADMIN").id == u.id  # tidak peka huruf besar
    with pytest.raises(ValueError):
        store.create_user(username="admin", password_hash="h", role="qa")
    token = store.create_session(u.id, ttl_seconds=60, max_age_seconds=3600)
    assert store.session_user(token).username == "admin"
    assert store.session_user("palsu") is None
    store.delete_session(token)
    assert store.session_user(token) is None
    expired = store.create_session(u.id, ttl_seconds=-1, max_age_seconds=3600)
    assert store.session_user(expired) is None


@pytest.fixture
def server(tmp_path):
    settings = ServerSettings(data_dir=tmp_path / "data", auth_required=True)
    app = create_app(settings, secrets=MemorySecretStore())
    with TestClient(app) as client:
        store = app.state.store
        store.create_user(username="admin", password_hash=hash_password("admin-pass-1"), role="admin")
        store.create_user(username="qa", password_hash=hash_password("qa-pass-123"), role="qa")
        store.create_user(username="lihat", password_hash=hash_password("viewer-pass"), role="viewer")
        yield client, app


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=H)


def test_requires_login(server):
    client, _ = server
    assert client.get("/api/auth/status").json() == {"auth_required": True, "user": None}
    assert client.get("/api/apps").status_code == 401
    assert login(client, "admin", "salah").status_code == 401
    r = login(client, "admin", "admin-pass-1")
    assert r.status_code == 200 and r.json()["user"] == {"id": 1, "username": "admin", "role": "admin"}
    cookie = r.cookies.get("qa_session") or client.cookies.get("qa_session")
    assert cookie
    assert client.get("/api/apps").status_code == 200
    assert client.get("/api/auth/status").json()["user"]["username"] == "admin"
    assert client.post("/api/auth/logout", headers=H).status_code == 204
    assert client.get("/api/apps").status_code == 401


def test_csrf_header_required_for_writes(server):
    client, _ = server
    login(client, "admin", "admin-pass-1")
    r = client.post("/api/apps", json={"name": "X", "url": "http://x.test"})
    assert r.status_code == 403 and "X-QA-Agent" in r.json()["detail"]
    assert client.post("/api/apps", json={"name": "X", "url": "http://x.test"}, headers=H).status_code == 201


def test_roles(server):
    client, _ = server
    login(client, "lihat", "viewer-pass")
    assert client.get("/api/runs").status_code == 200
    assert client.post("/api/apps", json={"name": "X", "url": "http://x.test"}, headers=H).status_code == 403
    login(client, "qa", "qa-pass-123")
    assert client.post("/api/apps", json={"name": "X", "url": "http://x.test"}, headers=H).status_code == 201
    r = client.post("/api/profiles", json={"name": "P", "base_url": "http://x/v1", "model": "m"}, headers=H)
    assert r.status_code == 403 and "Admin" in r.json()["detail"]
    assert client.get("/api/users").status_code == 403
    login(client, "admin", "admin-pass-1")
    assert client.post("/api/profiles", json={"name": "P", "base_url": "http://x/v1", "model": "m"}, headers=H).status_code == 201


def test_user_management_and_own_password(server):
    client, _ = server
    login(client, "admin", "admin-pass-1")
    r = client.post("/api/users", json={"username": "budi", "password": "budi-pass-1", "role": "qa"}, headers=H)
    assert r.status_code == 201 and "password" not in r.text
    uid = r.json()["id"]
    assert client.post("/api/users", json={"username": "x", "password": "pendek", "role": "qa"}, headers=H).status_code == 422
    assert client.patch(f"/api/users/{uid}", json={"role": "viewer"}, headers=H).json()["role"] == "viewer"
    assert client.patch(f"/api/users/{uid}", json={"password": "baru-pass-99"}, headers=H).status_code == 200
    names = [u["username"] for u in client.get("/api/users").json()]
    assert names == ["admin", "qa", "lihat", "budi"]
    # admin terakhir tidak boleh dihapus / diturunkan
    assert client.patch("/api/users/1", json={"role": "qa"}, headers=H).status_code == 409
    assert client.delete("/api/users/1", headers=H).status_code == 409
    login(client, "budi", "baru-pass-99")
    r = client.post("/api/auth/password", json={"current": "salah", "new": "lebih-baru-1"}, headers=H)
    assert r.status_code == 422
    assert client.post("/api/auth/password", json={"current": "baru-pass-99", "new": "lebih-baru-1"}, headers=H).status_code == 204
    assert login(client, "budi", "lebih-baru-1").status_code == 200


def test_disabled_user_and_rate_limit(server):
    client, app = server
    login(client, "admin", "admin-pass-1")
    uid = client.post("/api/users", json={"username": "nonaktif", "password": "pass-1234", "role": "qa"}, headers=H).json()["id"]
    client.patch(f"/api/users/{uid}", json={"active": False}, headers=H)
    assert login(client, "nonaktif", "pass-1234").status_code == 401
    for _ in range(5):
        login(client, "qa", "salah")
    r = login(client, "qa", "qa-pass-123")
    assert r.status_code == 429 and "5 menit" in r.json()["detail"]


def test_websocket_requires_session(server):
    client, app = server
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events") as ws:
            ws.receive_json()
    login(client, "lihat", "viewer-pass")
    with client.websocket_connect("/ws/events") as ws:
        app.state.hub.publish_global({"type": "run.status", "run_id": 1, "status": "running"})
        assert ws.receive_json()["status"] == "running"


def test_local_mode_has_no_login(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path / "d"), secrets=MemorySecretStore())
    with TestClient(app) as client:
        assert client.get("/api/auth/status").json() == {"auth_required": False, "user": None}
        assert client.post("/api/apps", json={"name": "X", "url": "http://x.test"}).status_code == 201


def test_run_records_creator(server):
    client, app = server
    login(client, "qa", "qa-pass-123")
    store = app.state.store
    store.create_profile(name="P", provider="openai_compatible", base_url="http://x/v1", model="m")
    a = client.post("/api/apps", json={"name": "X", "url": "http://x.test"}, headers=H).json()
    app.state.manager._enqueue = lambda run_id: None
    run = client.post("/api/runs", json={"app_id": a["id"], "mode": "explore"}, headers=H).json()
    assert run["created_by"] == "qa"
