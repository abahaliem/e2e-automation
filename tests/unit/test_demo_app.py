import pytest

from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, create_app


@pytest.fixture
def client():
    app = create_app()
    c = app.test_client()
    c.state = app.config["STATE"]
    return c


def login(client):
    return client.post("/login", data={"email": DEMO_USER, "password": DEMO_PASSWORD})


def test_requires_login(client):
    resp = client.get("/users")
    assert resp.status_code == 302 and "/login?next=/users" in resp.headers["Location"]


def test_login_not_counted_as_write(client):
    assert login(client).status_code == 302
    assert client.state.writes == []


def test_wrong_password_shows_alert(client):
    resp = client.post("/login", data={"email": DEMO_USER, "password": "salah"})
    assert "Email atau password salah" in resp.get_data(as_text=True)


def test_create_user_valid(client):
    login(client)
    resp = client.post("/users", data={"name": "Andi", "email": "andi@demo.local", "age": "22"})
    assert resp.status_code == 302
    assert len(client.state.users) == 3
    assert client.state.writes == ["POST /users"]


def test_bug_invalid_email_accepted(client):
    login(client)
    assert client.post("/users", data={"name": "Andi", "email": "bukan-email", "age": "22"}).status_code == 302


def test_bug_apostrophe_returns_500(client):
    login(client)
    assert client.post("/users", data={"name": "O'Brien", "email": "o@demo.local", "age": "40"}).status_code == 500


def test_empty_name_validation(client):
    login(client)
    resp = client.post("/users", data={"name": "", "email": "x@demo.local", "age": "22"})
    assert resp.status_code == 400 and "Nama wajib diisi" in resp.get_data(as_text=True)


def test_reports_rebuild_counted_and_reset(client):
    login(client)
    client.post("/reports/rebuild")
    assert client.get("/__test__/writes").get_json()["count"] == 1
    client.post("/__test__/reset")
    assert client.state.writes == [] and len(client.state.users) == 2
