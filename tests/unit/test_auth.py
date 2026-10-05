import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.orchestrator.auth import AuthManager, LoginFailed, auth_state_path
from tests.fakes import FakeDriver, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna"))
USERS = screen("users", el(1, "link", "Dashboard"))


def outcome(status="pass", final="done"):
    return LoopOutcome(final=final, status=status, actual="hasil login")


def test_auth_state_path(tmp_path):
    p = auth_state_path(tmp_path, "https://app-dev.kantor.local:8443", "Admin QA")
    assert p == tmp_path / ".qa-agent" / "auth" / "app-dev-kantor-local-8443-admin-qa.json"


def test_login_success_saves_state(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    calls = []

    def run_login(tc_id, goal):
        calls.append((tc_id, goal))
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").login()
    assert driver.saved == [tmp_path / "s.json"]
    tc_id, goal = calls[0]
    assert tc_id.startswith("LOGIN-") and "{{password}}" in goal and "'admin'" in goal


def test_login_ids_are_unique(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    ids = []

    def run_login(tc_id, goal):
        ids.append(tc_id)
        driver.current = url("home")
        return outcome()

    auth = AuthManager(driver, run_login, tmp_path / "s.json", "admin")
    auth.login()
    driver.current = url("login")
    auth.login()
    assert len(set(ids)) == 2


def test_login_failure_raises(tmp_path):
    driver = FakeDriver([LOGIN], url("login"))
    auth = AuthManager(driver, lambda t, g: outcome("fail"), tmp_path / "s.json", "admin")
    with pytest.raises(LoginFailed, match="hasil login"):
        auth.login()
    assert driver.saved == []


def test_login_claimed_pass_but_form_still_shown(tmp_path):
    driver = FakeDriver([LOGIN], url("login"))
    auth = AuthManager(driver, lambda t, g: outcome(), tmp_path / "s.json", "admin")
    with pytest.raises(LoginFailed, match="masih tampil"):
        auth.login()


def test_start_authenticated_reuses_session(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    auth = AuthManager(driver, lambda t, g: pytest.fail("tidak boleh login ulang"), tmp_path / "s.json", "admin")
    auth.start_authenticated(url("home"))
    assert driver.sessions == [tmp_path / "s.json"] and driver.current == url("home")


class RedirectDriver(FakeDriver):
    logged_in = False

    def goto(self, location):
        super().goto(location if self.logged_in else url("login"))


def test_start_authenticated_logs_in_when_redirected(tmp_path):
    driver = RedirectDriver([LOGIN, HOME], url("login"))

    def run_login(tc_id, goal):
        driver.logged_in = True
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").start_authenticated(url("home"))
    assert driver.current == url("home") and driver.saved


def test_relogin_returns_to_page(tmp_path):
    driver = FakeDriver([LOGIN, HOME, USERS], url("login"))

    def run_login(tc_id, goal):
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").relogin(url("users"))
    assert driver.current == url("users")
