"""Indeks SQLite untuk dashboard. Evidence tetap di folder run; tabel ini bisa dibangun ulang dari folder."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qa_agent.evidence import RunStore, now_iso
from qa_agent.models import QaTestCase

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'web',
  url TEXT NOT NULL DEFAULT '',
  allowed_domains TEXT NOT NULL DEFAULT '[]',
  login_endpoints TEXT NOT NULL DEFAULT '[]',
  default_profile_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'default',
  username TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  base_url TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL,
  vision INTEGER NOT NULL DEFAULT 1,
  timeout_seconds INTEGER NOT NULL DEFAULT 120,
  is_default INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL REFERENCES apps(id),
  mode TEXT NOT NULL,
  module TEXT,
  environment TEXT NOT NULL,
  profile_id INTEGER,
  account_id INTEGER,
  status TEXT NOT NULL DEFAULT 'queued',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  folder TEXT NOT NULL,
  counts TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  options TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  filename TEXT NOT NULL,
  pages INTEGER NOT NULL DEFAULT 1,
  chars INTEGER NOT NULL DEFAULT 0,
  stages TEXT NOT NULL DEFAULT '[]',
  app_ids TEXT NOT NULL DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  set_name TEXT NOT NULL COLLATE NOCASE,
  value TEXT NOT NULL,
  used_by TEXT,
  used_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(app_id, set_name, value)
);
CREATE TABLE IF NOT EXISTS hooks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  run_when TEXT NOT NULL DEFAULT 'case',
  method TEXT NOT NULL DEFAULT 'POST',
  url TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  capture TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  name TEXT NOT NULL COLLATE NOCASE,
  steps TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(app_id, name)
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'qa',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at REAL NOT NULL,
  last_seen REAL NOT NULL,
  expires_at REAL NOT NULL,
  ttl REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_cases_index (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  tc_id TEXT NOT NULL,
  module TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT '',
  status_ai TEXT,
  status_final TEXT,
  severity TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, tc_id)
);
"""

# Run yang sedang dikerjakan worker. "paused" di database = sudah berhenti (mis. menunggu review / AI bermasalah)
# dan tetap bisa dilanjutkan, jadi tidak diubah jadi Terhenti saat server menyala ulang.
UNFINISHED = ("queued", "running")


class AppRow(BaseModel):
    id: int
    name: str
    platform: str = "web"
    url: str = ""
    allowed_domains: list[str] = Field(default_factory=list)
    login_endpoints: list[str] = Field(default_factory=list)
    default_profile_id: int | None = None


class AccountRow(BaseModel):
    id: int
    app_id: int
    role: str
    username: str


class ProfileRow(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str = ""
    model: str
    vision: bool = True
    timeout_seconds: int = 120
    is_default: bool = False


class RunRow(BaseModel):
    id: int
    app_id: int
    mode: str
    module: str | None = None
    environment: str
    profile_id: int | None = None
    account_id: int | None = None
    status: str
    started_at: str
    finished_at: str | None = None
    folder: str
    counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""
    model: str = ""
    options: dict[str, Any] = Field(default_factory=dict)


class TestDataRow(BaseModel):
    """Satu nilai data uji (mis. wo_id = 000090014541); dipakai sekali lalu ditandai terpakai."""
    __test__ = False
    id: int
    app_id: int
    set_name: str
    value: str
    used_by: str | None = None
    used_at: str | None = None


class HookRow(BaseModel):
    """Persiapan HTTP sebelum run / test case (header disimpan di penyimpanan rahasia, bukan di sini)."""
    id: int
    app_id: int
    name: str
    when: str = "case"
    method: str = "POST"
    url: str
    body: str = ""
    capture: dict[str, str] = Field(default_factory=dict)
    active: bool = True


class FlowRow(BaseModel):
    """Modul kustom: alur bisnis yang ditulis QA (mis. buka WO sampai Closed)."""
    id: int
    app_id: int
    name: str
    steps: str
    created_at: str = ""
    updated_at: str = ""


class UserRow(BaseModel):
    id: int
    username: str
    role: str
    active: bool = True
    created_at: str = ""
    last_login: str | None = None
    password_hash: str = Field(default="", exclude=True)  # tidak pernah ikut ke JSON


class SkillRow(BaseModel):
    id: int
    name: str
    filename: str
    pages: int = 1
    chars: int = 0
    stages: list[str] = Field(default_factory=list)
    app_ids: list[int] = Field(default_factory=list)  # kosong = semua aplikasi
    active: bool = True
    created_at: str = ""


class CaseRow(BaseModel):
    run_id: int
    tc_id: str
    module: str = ""
    title: str
    type: str = ""
    status_ai: str | None = None
    status_final: str | None = None
    severity: str | None = None

    @property
    def effective_status(self) -> str | None:
        return self.status_final or self.status_ai


def _counts(cases: list[QaTestCase]) -> dict[str, int]:
    return dict(Counter(c.effective_status for c in cases if c.effective_status))


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---------- util ----------
    def _exec(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    @staticmethod
    def _app(row: sqlite3.Row | None) -> AppRow | None:
        if row is None:
            return None
        d = dict(row)
        d["allowed_domains"] = json.loads(d["allowed_domains"])
        d["login_endpoints"] = json.loads(d["login_endpoints"])
        return AppRow.model_validate(d)

    @staticmethod
    def _run(row: sqlite3.Row | None) -> RunRow | None:
        if row is None:
            return None
        d = dict(row)
        d["counts"] = json.loads(d["counts"])
        d["options"] = json.loads(d["options"])
        return RunRow.model_validate(d)

    @staticmethod
    def _profile(row: sqlite3.Row | None) -> ProfileRow | None:
        return None if row is None else ProfileRow.model_validate(dict(row))

    # ---------- pengguna & sesi (mode server) ----------
    @staticmethod
    def _user(row: sqlite3.Row | None) -> UserRow | None:
        if row is None:
            return None
        d = dict(row)
        d["active"] = bool(d["active"])
        return UserRow.model_validate(d)

    def create_user(self, *, username: str, password_hash: str, role: str) -> UserRow:
        try:
            cur = self._exec("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                             (username.strip(), password_hash, role, now_iso()))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Username '{username}' sudah dipakai") from e
        return self.get_user(cur.lastrowid)  # type: ignore[return-value]

    def get_user(self, user_id: int) -> UserRow | None:
        return self._user(self._one("SELECT * FROM users WHERE id=?", (user_id,)))

    def get_user_by_name(self, username: str) -> UserRow | None:
        return self._user(self._one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)))

    def list_users(self) -> list[UserRow]:
        return [self._user(r) for r in self._all("SELECT * FROM users ORDER BY id")]  # type: ignore[misc]

    def update_user(self, user_id: int, **fields: Any) -> UserRow:
        allowed = {"role", "active", "password_hash", "last_login"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Kolom tidak dikenal: {key}")
            sets.append(f"{key}=?")
            params.append(int(bool(value)) if key == "active" else value)
        if sets:
            self._exec(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*params, user_id))
        user = self.get_user(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def delete_user(self, user_id: int) -> None:
        self._exec("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self._exec("DELETE FROM users WHERE id=?", (user_id,))

    def count_active_admins(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1")["n"]  # type: ignore[index]

    def create_session(self, user_id: int, *, ttl_seconds: float, max_age_seconds: float) -> str:
        import hashlib
        import secrets as pysecrets
        import time

        token = pysecrets.token_urlsafe(32)
        now = time.time()
        self._exec("INSERT INTO sessions (token_hash, user_id, created_at, last_seen, expires_at, ttl) VALUES (?,?,?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), user_id, now, now, now + max_age_seconds, ttl_seconds))
        return token

    def session_user(self, token: str | None) -> UserRow | None:
        """Pengguna dari token sesi; sesi kedaluwarsa (tidak aktif / melewati umur maksimal) dihapus."""
        import hashlib
        import time

        if not token:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        row = self._one("SELECT * FROM sessions WHERE token_hash=?", (key,))
        if row is None:
            return None
        now = time.time()
        if now > row["expires_at"] or now - row["last_seen"] > row["ttl"]:
            self._exec("DELETE FROM sessions WHERE token_hash=?", (key,))
            return None
        user = self.get_user(row["user_id"])
        if user is None or not user.active:
            return None
        self._exec("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, key))
        return user

    def delete_session(self, token: str | None) -> None:
        import hashlib

        if token:
            self._exec("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def delete_user_sessions(self, user_id: int) -> None:
        self._exec("DELETE FROM sessions WHERE user_id=?", (user_id,))

    # ---------- skill QA ----------
    @staticmethod
    def _skill(row: sqlite3.Row | None) -> SkillRow | None:
        if row is None:
            return None
        d = dict(row)
        d["stages"] = json.loads(d["stages"])
        d["app_ids"] = json.loads(d["app_ids"])
        d["active"] = bool(d["active"])
        return SkillRow.model_validate(d)

    def create_skill(self, *, name: str, filename: str, pages: int, chars: int, stages: list[str],
                     app_ids: list[int] | None = None, active: bool = True) -> SkillRow:
        cur = self._exec(
            "INSERT INTO skills (name, filename, pages, chars, stages, app_ids, active, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, filename, pages, chars, json.dumps(stages), json.dumps(app_ids or []), int(active), now_iso()))
        return self.get_skill(cur.lastrowid)  # type: ignore[return-value]

    def get_skill(self, skill_id: int) -> SkillRow | None:
        return self._skill(self._one("SELECT * FROM skills WHERE id=?", (skill_id,)))

    def list_skills(self) -> list[SkillRow]:
        return [self._skill(r) for r in self._all("SELECT * FROM skills ORDER BY id")]  # type: ignore[misc]

    def update_skill(self, skill_id: int, **fields: Any) -> SkillRow:
        allowed = {"name", "stages", "app_ids", "active"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Kolom tidak dikenal: {key}")
            if key in ("stages", "app_ids"):
                value = json.dumps(value or [])
            if key == "active":
                value = int(bool(value))
            sets.append(f"{key}=?")
            params.append(value)
        if sets:
            self._exec(f"UPDATE skills SET {', '.join(sets)} WHERE id=?", (*params, skill_id))
        skill = self.get_skill(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        return skill

    def delete_skill(self, skill_id: int) -> None:
        self._exec("DELETE FROM skills WHERE id=?", (skill_id,))

    def skills_for(self, *, app_id: int, stages: tuple[str, ...]) -> list[SkillRow]:
        """Skill aktif yang berlaku untuk aplikasi ini dan dipakai di salah satu tahap."""
        return [s for s in self.list_skills()
                if s.active and (not s.app_ids or app_id in s.app_ids) and set(s.stages) & set(stages)]

    # ---------- data uji ----------
    def add_test_data(self, app_id: int, set_name: str, values: list[str]) -> int:
        added = 0
        with self._lock:
            for value in values:
                value = value.strip()
                if not value:
                    continue
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO test_data (app_id, set_name, value, created_at) VALUES (?,?,?,?)",
                    (app_id, set_name.strip(), value, now_iso()))
                added += cur.rowcount
            self._db.commit()
        return added

    def list_test_data(self, app_id: int) -> list[TestDataRow]:
        return [TestDataRow.model_validate(dict(r)) for r in
                self._all("SELECT * FROM test_data WHERE app_id=? ORDER BY set_name, id", (app_id,))]

    def take_test_data(self, app_id: int, set_name: str, used_by: str) -> str | None:
        """Ambil nilai tersedia berikutnya dan tandai terpakai (atomik)."""
        with self._lock:
            row = self._db.execute(
                "SELECT id, value FROM test_data WHERE app_id=? AND set_name=? COLLATE NOCASE AND used_by IS NULL "
                "ORDER BY id LIMIT 1", (app_id, set_name.strip())).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE test_data SET used_by=?, used_at=? WHERE id=?", (used_by, now_iso(), row["id"]))
            self._db.commit()
            return row["value"]

    def get_test_data(self, value_id: int) -> TestDataRow | None:
        row = self._one("SELECT * FROM test_data WHERE id=?", (value_id,))
        return None if row is None else TestDataRow.model_validate(dict(row))

    def peek_test_data(self, app_id: int, set_name: str) -> str | None:
        """Nilai pertama kumpulan (yang tersedia lebih dulu) tanpa menandainya terpakai."""
        row = self._one("SELECT value FROM test_data WHERE app_id=? AND set_name=? COLLATE NOCASE "
                        "ORDER BY used_by IS NOT NULL, id LIMIT 1", (app_id, set_name.strip()))
        return None if row is None else row["value"]

    def release_test_data(self, app_id: int, set_name: str, value: str) -> None:
        self._exec("UPDATE test_data SET used_by=NULL, used_at=NULL WHERE app_id=? AND set_name=? COLLATE NOCASE "
                   "AND value=?", (app_id, set_name.strip(), value))

    def reset_test_data(self, value_id: int) -> None:
        self._exec("UPDATE test_data SET used_by=NULL, used_at=NULL WHERE id=?", (value_id,))

    def delete_test_data(self, value_id: int) -> None:
        self._exec("DELETE FROM test_data WHERE id=?", (value_id,))

    def delete_test_data_set(self, app_id: int, set_name: str) -> None:
        self._exec("DELETE FROM test_data WHERE app_id=? AND set_name=? COLLATE NOCASE", (app_id, set_name.strip()))

    # ---------- persiapan HTTP ----------
    @staticmethod
    def _hook(row: sqlite3.Row | None) -> HookRow | None:
        if row is None:
            return None
        d = dict(row)
        d["when"] = d.pop("run_when")
        d["capture"] = json.loads(d["capture"] or "{}")
        d["active"] = bool(d["active"])
        return HookRow.model_validate(d)

    def create_hook(self, *, app_id: int, name: str, when: str = "case", method: str = "POST", url: str,
                    body: str = "", capture: dict[str, str] | None = None) -> HookRow:
        cur = self._exec("INSERT INTO hooks (app_id, name, run_when, method, url, body, capture, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (app_id, name.strip(), when, method.upper(), url.strip(), body, json.dumps(capture or {}),
                          now_iso()))
        return self.get_hook(cur.lastrowid)  # type: ignore[return-value]

    def get_hook(self, hook_id: int) -> HookRow | None:
        return self._hook(self._one("SELECT * FROM hooks WHERE id=?", (hook_id,)))

    def list_hooks(self, app_id: int, *, when: str | None = None, active_only: bool = False) -> list[HookRow]:
        sql, params = "SELECT * FROM hooks WHERE app_id=?", [app_id]
        if when:
            sql += " AND run_when=?"
            params.append(when)
        if active_only:
            sql += " AND active=1"
        return [self._hook(r) for r in self._all(sql + " ORDER BY id", tuple(params))]  # type: ignore[misc]

    def update_hook(self, hook_id: int, **fields: Any) -> HookRow:
        columns = {"name": "name", "when": "run_when", "method": "method", "url": "url", "body": "body",
                   "capture": "capture", "active": "active"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in columns:
                raise ValueError(f"Kolom tidak dikenal: {key}")
            if key == "capture":
                value = json.dumps(value or {})
            elif key == "active":
                value = int(bool(value))
            elif key == "method":
                value = str(value).upper()
            sets.append(f"{columns[key]}=?")
            params.append(value)
        if sets:
            self._exec(f"UPDATE hooks SET {', '.join(sets)} WHERE id=?", (*params, hook_id))
        hook = self.get_hook(hook_id)
        if hook is None:
            raise KeyError(hook_id)
        return hook

    def delete_hook(self, hook_id: int) -> None:
        self._exec("DELETE FROM hooks WHERE id=?", (hook_id,))

    # ---------- modul kustom (alur bisnis) ----------
    def create_flow(self, *, app_id: int, name: str, steps: str) -> FlowRow:
        now = now_iso()
        try:
            cur = self._exec("INSERT INTO flows (app_id, name, steps, created_at, updated_at) VALUES (?,?,?,?,?)",
                             (app_id, name.strip(), steps, now, now))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"name::Alur '{name.strip()}' sudah ada di aplikasi ini") from e
        return self.get_flow(cur.lastrowid)  # type: ignore[return-value]

    def get_flow(self, flow_id: int) -> FlowRow | None:
        row = self._one("SELECT * FROM flows WHERE id=?", (flow_id,))
        return None if row is None else FlowRow.model_validate(dict(row))

    def list_flows(self, app_id: int) -> list[FlowRow]:
        return [FlowRow.model_validate(dict(r)) for r in self._all("SELECT * FROM flows WHERE app_id=? ORDER BY id", (app_id,))]

    def find_flow(self, app_id: int, name: str) -> FlowRow | None:
        row = self._one("SELECT * FROM flows WHERE app_id=? AND name=? COLLATE NOCASE", (app_id, " ".join(name.split())))
        return None if row is None else FlowRow.model_validate(dict(row))

    def update_flow(self, flow_id: int, *, name: str | None = None, steps: str | None = None) -> FlowRow:
        flow = self.get_flow(flow_id)
        if flow is None:
            raise KeyError(flow_id)
        try:
            self._exec("UPDATE flows SET name=?, steps=?, updated_at=? WHERE id=?",
                       ((name or flow.name).strip(), steps if steps is not None else flow.steps, now_iso(), flow_id))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"name::Alur '{name}' sudah ada di aplikasi ini") from e
        return self.get_flow(flow_id)  # type: ignore[return-value]

    def delete_flow(self, flow_id: int) -> None:
        self._exec("DELETE FROM flows WHERE id=?", (flow_id,))

    # ---------- pengaturan umum (key-value) ----------
    def get_setting(self, key: str) -> str | None:
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return None if row is None else row["value"]

    def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            self._exec("DELETE FROM settings WHERE key=?", (key,))
        else:
            self._exec("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))

    # ---------- apps ----------
    def create_app(self, *, name: str, platform: str = "web", url: str = "", allowed_domains: list[str] | None = None,
                   login_endpoints: list[str] | None = None, default_profile_id: int | None = None) -> AppRow:
        cur = self._exec(
            "INSERT INTO apps (name, platform, url, allowed_domains, login_endpoints, default_profile_id, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (name, platform, url, json.dumps(allowed_domains or []), json.dumps(login_endpoints or []),
             default_profile_id, now_iso()))
        return self.get_app(cur.lastrowid)  # type: ignore[return-value]

    def get_app(self, app_id: int) -> AppRow | None:
        return self._app(self._one("SELECT * FROM apps WHERE id=?", (app_id,)))

    def list_apps(self) -> list[AppRow]:
        return [self._app(r) for r in self._all("SELECT * FROM apps ORDER BY name COLLATE NOCASE")]  # type: ignore[misc]

    def update_app(self, app_id: int, **fields: Any) -> AppRow:
        allowed = {"name", "platform", "url", "allowed_domains", "login_endpoints", "default_profile_id"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Kolom tidak dikenal: {key}")
            if key in ("allowed_domains", "login_endpoints"):
                value = json.dumps(value or [])
            sets.append(f"{key}=?")
            params.append(value)
        if sets:
            self._exec(f"UPDATE apps SET {', '.join(sets)} WHERE id=?", (*params, app_id))
        app = self.get_app(app_id)
        if app is None:
            raise KeyError(app_id)
        return app

    def delete_app(self, app_id: int) -> None:
        """Hapus aplikasi beserta akun, alur, data uji, dan persiapannya. Run harus sudah dihapus lebih dulu."""
        if self._one("SELECT 1 FROM runs WHERE app_id=? LIMIT 1", (app_id,)):
            raise ValueError("Aplikasi sudah punya riwayat run. Hapus beserta riwayat run-nya untuk melanjutkan")
        with self._lock:
            for table in ("accounts", "flows", "test_data", "hooks"):
                self._db.execute(f"DELETE FROM {table} WHERE app_id=?", (app_id,))
            self._db.execute("DELETE FROM apps WHERE id=?", (app_id,))
            self._db.commit()

    # ---------- akun ----------
    def create_account(self, *, app_id: int, role: str, username: str) -> AccountRow:
        cur = self._exec("INSERT INTO accounts (app_id, role, username) VALUES (?,?,?)", (app_id, role, username))
        return self.get_account(cur.lastrowid)  # type: ignore[return-value]

    def get_account(self, account_id: int) -> AccountRow | None:
        row = self._one("SELECT * FROM accounts WHERE id=?", (account_id,))
        return None if row is None else AccountRow.model_validate(dict(row))

    def list_accounts(self, app_id: int) -> list[AccountRow]:
        return [AccountRow.model_validate(dict(r)) for r in
                self._all("SELECT * FROM accounts WHERE app_id=? ORDER BY id", (app_id,))]

    def delete_account(self, account_id: int) -> None:
        self._exec("DELETE FROM accounts WHERE id=?", (account_id,))

    # ---------- profil AI ----------
    def create_profile(self, *, name: str, provider: str, model: str, base_url: str = "", vision: bool = True,
                       timeout_seconds: int = 120, is_default: bool = False) -> ProfileRow:
        with self._lock:
            if is_default or not self._one("SELECT 1 FROM ai_profiles LIMIT 1"):
                self._db.execute("UPDATE ai_profiles SET is_default=0")
                is_default = True
            cur = self._db.execute(
                "INSERT INTO ai_profiles (name, provider, base_url, model, vision, timeout_seconds, is_default)"
                " VALUES (?,?,?,?,?,?,?)",
                (name, provider, base_url, model, int(vision), timeout_seconds, int(is_default)))
            self._db.commit()
            return self.get_profile(cur.lastrowid)  # type: ignore[return-value]

    def get_profile(self, profile_id: int) -> ProfileRow | None:
        return self._profile(self._one("SELECT * FROM ai_profiles WHERE id=?", (profile_id,)))

    def list_profiles(self) -> list[ProfileRow]:
        return [self._profile(r) for r in self._all("SELECT * FROM ai_profiles ORDER BY id")]  # type: ignore[misc]

    def get_default_profile(self) -> ProfileRow | None:
        return self._profile(self._one("SELECT * FROM ai_profiles WHERE is_default=1 LIMIT 1"))

    def update_profile(self, profile_id: int, **fields: Any) -> ProfileRow:
        allowed = {"name", "provider", "base_url", "model", "vision", "timeout_seconds", "is_default"}
        with self._lock:
            sets, params = [], []
            for key, value in fields.items():
                if key not in allowed:
                    raise ValueError(f"Kolom tidak dikenal: {key}")
                if key in ("vision", "is_default"):
                    value = int(bool(value))
                sets.append(f"{key}=?")
                params.append(value)
            if fields.get("is_default"):
                self._db.execute("UPDATE ai_profiles SET is_default=0")
            if sets:
                self._db.execute(f"UPDATE ai_profiles SET {', '.join(sets)} WHERE id=?", (*params, profile_id))
            self._db.commit()
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        return profile

    def delete_profile(self, profile_id: int) -> None:
        with self._lock:
            was_default = self._one("SELECT is_default FROM ai_profiles WHERE id=?", (profile_id,))
            self._db.execute("DELETE FROM ai_profiles WHERE id=?", (profile_id,))
            if was_default and was_default["is_default"]:
                self._db.execute("UPDATE ai_profiles SET is_default=1 WHERE id=(SELECT MIN(id) FROM ai_profiles)")
            self._db.commit()

    # ---------- run ----------
    def create_run(self, *, app_id: int, mode: str, environment: str, folder: str, module: str | None = None,
                   profile_id: int | None = None, account_id: int | None = None, status: str = "queued",
                   started_at: str | None = None, model: str = "", options: dict | None = None) -> RunRow:
        cur = self._exec(
            "INSERT INTO runs (app_id, mode, module, environment, profile_id, account_id, status, started_at, folder,"
            " model, options) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (app_id, mode, module, environment, profile_id, account_id, status, started_at or now_iso(), folder,
             model, json.dumps(options or {})))
        return self.get_run(cur.lastrowid)  # type: ignore[return-value]

    def get_run(self, run_id: int) -> RunRow | None:
        return self._run(self._one("SELECT * FROM runs WHERE id=?", (run_id,)))

    def update_run(self, run_id: int, **fields: Any) -> RunRow:
        allowed = {"status", "started_at", "finished_at", "folder", "counts", "note", "model", "module", "options"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Kolom tidak dikenal: {key}")
            if key in ("counts", "options"):
                value = json.dumps(value or {})
            sets.append(f"{key}=?")
            params.append(value)
        if sets:
            self._exec(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", (*params, run_id))
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def list_runs(self, status: str | None = None, app_id: int | None = None, limit: int = 50) -> list[RunRow]:
        where, params = [], []
        if status:
            statuses = status.split(",")
            where.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if app_id is not None:
            where.append("app_id=?")
            params.append(app_id)
        sql = "SELECT * FROM runs" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY id DESC LIMIT ?"
        return [self._run(r) for r in self._all(sql, (*params, limit))]  # type: ignore[misc]

    def mark_unfinished_interrupted(self) -> int:
        cur = self._exec(
            f"UPDATE runs SET status='interrupted', note=CASE WHEN note='' THEN 'Server berhenti saat run berjalan'"
            f" ELSE note END WHERE status IN ({','.join('?' * len(UNFINISHED))})", UNFINISHED)
        return cur.rowcount

    def latest_completed_explore(self, app_id: int) -> RunRow | None:
        return self._run(self._one(
            "SELECT * FROM runs WHERE app_id=? AND mode='explore' AND status='completed' ORDER BY id DESC LIMIT 1",
            (app_id,)))

    # ---------- test case ----------
    def upsert_cases(self, run_id: int, cases: list[QaTestCase]) -> None:
        with self._lock:
            start = self._db.execute("SELECT COALESCE(MAX(position), 0) FROM test_cases_index WHERE run_id=?",
                                     (run_id,)).fetchone()[0]
            for n, c in enumerate(cases, 1):
                self._db.execute(
                    "INSERT INTO test_cases_index (run_id, tc_id, module, title, type, status_ai, status_final, severity,"
                    " position) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id, tc_id) DO UPDATE SET module=excluded.module,"
                    " title=excluded.title, type=excluded.type, status_ai=excluded.status_ai,"
                    " status_final=excluded.status_final, severity=excluded.severity",
                    (run_id, c.id, c.module, c.title, c.type, c.status_ai, c.status_final, c.severity, start + n))
            self._db.commit()

    def run_by_folder(self, folder: str) -> RunRow | None:
        return self._run(self._one("SELECT * FROM runs WHERE folder=? ORDER BY id DESC LIMIT 1", (folder,)))

    def delete_run(self, run_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM test_cases_index WHERE run_id=?", (run_id,))
            self._db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            self._db.commit()

    def replace_cases(self, run_id: int, cases: list[QaTestCase]) -> None:
        """Indeks test case diganti total (review: ada yang dihapus/diurutkan ulang)."""
        with self._lock:
            self._db.execute("DELETE FROM test_cases_index WHERE run_id=?", (run_id,))
            self._db.commit()
        self.upsert_cases(run_id, cases)

    def list_cases(self, run_id: int) -> list[CaseRow]:
        return [CaseRow.model_validate(dict(r)) for r in
                self._all("SELECT * FROM test_cases_index WHERE run_id=? ORDER BY position, tc_id", (run_id,))]

    def latest_findings(self, limit: int = 10) -> list[dict]:
        rows = self._all(
            "SELECT c.*, r.started_at, a.name AS app_name, a.platform FROM test_cases_index c"
            " JOIN runs r ON r.id=c.run_id JOIN apps a ON a.id=r.app_id"
            " WHERE COALESCE(c.status_final, c.status_ai) IN ('Fail', 'Perlu Review')"
            " ORDER BY r.id DESC, c.position LIMIT ?", (limit,))
        return [{"run_id": r["run_id"], "tc_id": r["tc_id"], "title": r["title"], "module": r["module"],
                 "status": r["status_final"] or r["status_ai"], "severity": r["severity"], "app_name": r["app_name"],
                 "platform": r["platform"], "started_at": r["started_at"]} for r in rows]

    # ---------- statistik ----------
    def _period(self, since: datetime, until: datetime) -> dict:
        lo, hi = since.isoformat(timespec="seconds"), until.isoformat(timespec="seconds")
        runs = self._all("SELECT r.id, a.platform FROM runs r JOIN apps a ON a.id=r.app_id"
                         " WHERE r.started_at >= ? AND r.started_at < ?", (lo, hi))
        statuses = [r[0] for r in self._all(
            "SELECT COALESCE(c.status_final, c.status_ai) FROM test_cases_index c JOIN runs r ON r.id=c.run_id"
            " WHERE r.started_at >= ? AND r.started_at < ?", (lo, hi))]
        counts = Counter(s for s in statuses if s)
        executed = sum(n for s, n in counts.items() if s != "Skipped")
        return {
            "total_runs": len(runs),
            "web_runs": sum(1 for r in runs if r["platform"] == "web"),
            "android_runs": sum(1 for r in runs if r["platform"] == "android"),
            "cases_executed": executed,
            "fail": counts.get("Fail", 0),
            "review": counts.get("Perlu Review", 0),
            "findings": counts.get("Fail", 0) + counts.get("Perlu Review", 0),
            "pass_rate": (counts.get("Pass", 0) / executed) if executed else None,
        }

    def stats(self, since: datetime, until: datetime) -> dict:
        current = self._period(since, until)
        previous = self._period(since - (until - since), since)
        current["pass_rate_prev"] = previous["pass_rate"]
        current["total_runs_prev"] = previous["total_runs"]
        current["findings_prev"] = previous["findings"]
        return current

    # ---------- impor folder CLI ----------
    def import_run_folder(self, path: Path, app_id: int) -> RunRow:
        path = Path(path)
        existing = self._one("SELECT id FROM runs WHERE folder=?", (str(path),))
        rs = RunStore(path)
        meta = rs.read_meta()
        cases = rs.read_testcases()
        if existing:
            run_id = existing["id"]
        else:
            run_id = self.create_run(app_id=app_id, mode=meta.mode, environment=meta.environment, folder=str(path),
                                     module=meta.module, status=meta.status, started_at=meta.started_at,
                                     model=meta.model).id
        self.update_run(run_id, status=meta.status, finished_at=meta.finished_at, counts=_counts(cases),
                        note=meta.note)
        self.upsert_cases(run_id, cases)
        return self.get_run(run_id)  # type: ignore[return-value]
