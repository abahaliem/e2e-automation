"""Aplikasi web demo dengan 3 bug buatan, target integration test & evaluasi QA Agent."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template_string, request, session
from werkzeug.serving import make_server

DEMO_USER = "admin@demo.local"
DEMO_PASSWORD = "rahasia123"

LAYOUT = """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>{{ title }} - Demo QA</title></head>
<body>
{% if logged_in %}
<nav aria-label="Menu utama">
  <a href="/">Dashboard</a>
  <a href="/users">Pengguna</a>
  <a href="/reports">Laporan</a>
  <form method="post" action="/logout" style="display:inline"><button type="submit">Keluar</button></form>
</nav>
{% endif %}
<main>{{ body|safe }}</main>
</body></html>"""

LOGIN = """<h1>Masuk</h1>
<form method="post">
  {% if error %}<div role="alert" class="error">{{ error }}</div>{% endif %}
  <p><label for="email">Email</label> <input id="email" name="email" type="text"></p>
  <p><label for="password">Password</label> <input id="password" name="password" type="password"></p>
  <button type="submit">Masuk</button>
</form>"""

DASHBOARD = """<h1>Dashboard</h1><p>Selamat datang di aplikasi demo QA.</p>"""

USERS = """<h1>Daftar Pengguna</h1>
<p><a href="/users/new">Tambah Pengguna</a> <button type="button">Ekspor</button></p>
<table>
  <tr><th>Nama</th><th>Email</th><th>Umur</th><th>Aksi</th></tr>
  {% for uid, u in users.items() %}
  <tr>
    <td>{{ u.name }}</td><td>{{ u.email }}</td><td>{{ u.age }}</td>
    <td><a href="/users/{{ uid }}/edit">Edit</a>
      <form method="post" action="/users/{{ uid }}/delete" style="display:inline"><button type="submit">Hapus</button></form></td>
  </tr>
  {% endfor %}
</table>"""

USER_FORM = """<form method="post" action="{{ action }}">
  <h2>{{ heading }}</h2>
  {% if error %}<div role="alert" class="error">{{ error }}</div>{% endif %}
  <p><label for="name">Nama</label> <input id="name" name="name" value="{{ user.name }}"></p>
  <p><label for="email">Email</label> <input id="email" name="email" value="{{ user.email }}"></p>
  <p><label for="age">Umur</label> <input id="age" name="age" value="{{ user.age }}"></p>
  <button type="submit">Simpan</button>
  <a href="/users">Batal</a>
</form>"""

REPORTS = """<h1>Laporan</h1>
<p>Ringkasan aktivitas pengguna.</p>
{% if done %}<p>Laporan sedang diproses ulang.</p>{% endif %}
<form method="post" action="/reports/rebuild"><button type="submit">Proses Ulang</button></form>"""

EMPTY_USER = {"name": "", "email": "", "age": ""}


@dataclass
class DemoState:
    users: dict[int, dict[str, str]] = field(default_factory=dict)
    next_id: int = 1
    writes: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.users = {
            1: {"name": "Budi Santoso", "email": "budi@demo.local", "age": "30"},
            2: {"name": "Siti Aminah", "email": "siti@demo.local", "age": "27"},
        }
        self.next_id = 3
        self.writes = []


def _validate(form) -> str:
    name = form.get("name", "").strip()
    if "'" in name:
        raise RuntimeError("Bug buatan #1: apostrof memicu error server")
    if not name:
        return "Nama wajib diisi"
    if not form.get("age", "").strip().isdigit():
        return "Umur harus angka"
    return ""  # Bug buatan #2: format email tidak divalidasi


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "demo-secret-key"
    state = DemoState()
    state.reset()
    app.config["STATE"] = state

    def page(title: str, body: str, **ctx):
        return render_template_string(LAYOUT, title=title, body=render_template_string(body, **ctx), logged_in="user" in session)

    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(f"/login?next={request.path}")
            return fn(*args, **kwargs)
        return wrapper

    @app.before_request
    def track_writes():
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path != "/login" and not request.path.startswith("/__test__"):
            state.writes.append(f"{request.method} {request.path}")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if request.form.get("email") == DEMO_USER and request.form.get("password") == DEMO_PASSWORD:
                session["user"] = DEMO_USER
                nxt = request.args.get("next", "/")
                return redirect(nxt if nxt.startswith("/") else "/")
            error = "Email atau password salah"
        return page("Masuk", LOGIN, error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    @login_required
    def dashboard():
        return page("Dashboard", DASHBOARD)

    @app.get("/users")
    @login_required
    def users():
        return page("Pengguna", USERS, users=state.users)

    @app.get("/users/new")
    @login_required
    def new_user():
        return page("Tambah Pengguna", USER_FORM, action="/users", heading="Tambah Pengguna", user=EMPTY_USER, error="")

    @app.post("/users")
    @login_required
    def create_user():
        error = _validate(request.form)
        data = {k: request.form.get(k, "").strip() for k in ("name", "email", "age")}
        if error:
            return page("Tambah Pengguna", USER_FORM, action="/users", heading="Tambah Pengguna", user=data, error=error), 400
        state.users[state.next_id] = data
        state.next_id += 1
        return redirect("/users")

    @app.get("/users/<int:uid>/edit")
    @login_required
    def edit_user(uid: int):
        user = state.users.get(uid)
        if user is None:
            abort(404)
        return page("Edit Pengguna", USER_FORM, action=f"/users/{uid}", heading="Edit Pengguna", user=user, error="")

    @app.post("/users/<int:uid>")
    @login_required
    def update_user(uid: int):
        if uid not in state.users:
            abort(404)
        error = _validate(request.form)
        data = {k: request.form.get(k, "").strip() for k in ("name", "email", "age")}
        if error:
            return page("Edit Pengguna", USER_FORM, action=f"/users/{uid}", heading="Edit Pengguna", user=data, error=error), 400
        state.users[uid] = data
        return redirect("/users")

    @app.post("/users/<int:uid>/delete")
    @login_required
    def delete_user(uid: int):
        state.users.pop(uid, None)
        return redirect("/users")

    @app.get("/reports")
    @login_required
    def reports():
        return page("Laporan", REPORTS, done=request.args.get("done") == "1")

    @app.post("/reports/rebuild")
    @login_required
    def rebuild_reports():
        return redirect("/reports?done=1")

    @app.get("/sw.js")
    def service_worker():
        return app.response_class("self.addEventListener('fetch', () => {});", mimetype="application/javascript")

    @app.get("/__test__/writes")
    def test_writes():
        return jsonify(count=len(state.writes), requests=state.writes)

    @app.post("/__test__/reset")
    def test_reset():
        state.reset()
        return jsonify(ok=True)

    return app


class DemoServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.app = create_app()
        self._server = make_server(host, port, self.app, threaded=True)
        self.url = f"http://{host}:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def state(self) -> DemoState:
        return self.app.config["STATE"]

    def start(self) -> "DemoServer":
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def stop(self) -> None:
        self._server.shutdown()
