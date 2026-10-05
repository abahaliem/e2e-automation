from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from qa_agent.agent.loop import LoopOutcome
from qa_agent.drivers.base import Driver
from qa_agent.evidence import slugify

LOGIN_GOAL = (
    "Login ke aplikasi memakai akun peran '<<role>>'. Isi field username/email dengan {{username}} "
    "dan field password dengan {{password}}, lalu klik tombol login/masuk. Nyatakan done dengan status pass "
    "jika sudah berhasil masuk (form login hilang), atau status fail jika login ditolak."
)


class LoginFailed(Exception):
    """Login otomatis tidak berhasil."""


def login_goal(role: str) -> str:
    return LOGIN_GOAL.replace("<<role>>", role)


def auth_state_path(project_dir: Path, target_url: str, role: str) -> Path:
    host = urlsplit(target_url).netloc or target_url
    return Path(project_dir) / ".qa-agent" / "auth" / f"{slugify(host)}-{slugify(role)}.json"


class AuthManager:
    def __init__(self, driver: Driver, run_login: Callable[[str, str], LoopOutcome], state_path: Path, role: str) -> None:
        self.driver = driver
        self.run_login = run_login
        self.state_path = Path(state_path)
        self.role = role
        self._count = 0

    def _next_id(self) -> str:
        self._count += 1
        return f"LOGIN-{datetime.now():%H%M%S}-{self._count}"

    def login(self) -> None:
        """Driver harus sedang berada di halaman login."""
        outcome = self.run_login(self._next_id(), login_goal(self.role))
        if outcome.final != "done" or outcome.status != "pass":
            raise LoginFailed(outcome.actual or outcome.reason or "Login tidak berhasil")
        if self.driver.observe().is_login_screen:
            raise LoginFailed("AI menyatakan berhasil, tetapi form login masih tampil")
        self.driver.save_auth_state(self.state_path)

    def start_authenticated(self, url: str) -> None:
        self.driver.new_session(self.state_path)
        self.driver.goto(url)
        if self.driver.observe().is_login_screen:
            self.login()
            self.driver.goto(url)
            if self.driver.observe().is_login_screen:
                raise LoginFailed("Masih diarahkan ke halaman login setelah login berhasil")

    def relogin(self, return_to: str) -> None:
        self.login()
        self.driver.goto(return_to)
