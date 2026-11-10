import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.evidence import RunStore
from qa_agent.llm.base import LLMUnavailable
from qa_agent.models import QaTestCase, Signal, StepRecord
from qa_agent.orchestrator.auth import LoginFailed
from qa_agent.orchestrator.deep import DeepRunner
from tests.fakes import FakeDriver, el, screen, url

HOME = screen("home", el(1, "link", "Pengguna"))
PASS = LoopOutcome(final="done", status="pass", actual="berhasil")


class StubLoop:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []
        self.relogin = "belum diset"

    def run(self, tc_id, goal, *, allow_logout=False, login=False):
        self.calls.append((tc_id, allow_logout))
        result = self.outcomes[tc_id]
        if isinstance(result, Exception):
            raise result
        return result


class StubAuth:
    def __init__(self, fail=False):
        self.fail = fail
        self.started = []

    def start_authenticated(self, target):
        if self.fail:
            raise LoginFailed("password salah")
        self.started.append(target)

    def relogin(self, return_to):
        pass


def tc(n, **kw):
    kw.setdefault("title", f"Kasus {n}")
    return QaTestCase(id=f"TC-PEN-00{n}", module="Pengguna", expected="ok", start_url=url("home"), **kw)


def make(tmp_path, outcomes, auth=None, **kw):
    store = RunStore(tmp_path / "run")
    loop = StubLoop(outcomes)
    driver = FakeDriver([HOME], url("home"))
    auth = auth or StubAuth()
    runner = DeepRunner(driver=driver, loop=loop, auth=auth, store=store, **kw)
    return runner, loop, store, driver, auth


def test_executes_and_judges(tmp_path):
    outcomes = {
        "TC-PEN-001": PASS,
        "TC-PEN-002": LoopOutcome(final="done", status="fail", actual="tanpa validasi"),
        "TC-PEN-003": LoopOutcome(final="done", status="pass", signals=[Signal(kind="http_error", message="x", status=500)]),
    }
    runner, loop, store, _, auth = make(tmp_path, outcomes)
    cases = runner.execute([tc(1), tc(2), tc(3)], needs_auth=True)
    assert [c.status_ai for c in cases] == ["Pass", "Perlu Review", "Fail"]
    assert cases[1].actual == "tanpa validasi" and cases[2].severity == "Major"
    assert auth.started == [url("home")] * 3
    assert loop.relogin == auth.relogin
    assert [c.status_ai for c in store.read_testcases()] == ["Pass", "Perlu Review", "Fail"]


def test_resume_skips_finished(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-002": PASS})
    runner.execute([tc(1, status_ai="Pass"), tc(2)], needs_auth=True)
    assert [c[0] for c in loop.calls] == ["TC-PEN-002"]


def test_logout_case_allows_logout(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-001": PASS})
    runner.execute([tc(1, title="Logout dari aplikasi")], needs_auth=True)
    assert loop.calls == [("TC-PEN-001", True)]


def test_public_module_uses_clean_session(tmp_path):
    runner, loop, _, driver, auth = make(tmp_path, {"TC-PEN-001": PASS})
    runner.execute([tc(1)], needs_auth=False)
    assert driver.sessions == [None] and driver.gotos == [url("home")]
    assert auth.started == [] and loop.relogin is None


def test_unexpected_error_blocks_case_and_continues(tmp_path):
    runner, _, _, driver, _ = make(tmp_path, {"TC-PEN-001": RuntimeError("elemen hilang"), "TC-PEN-002": PASS})
    cases = runner.execute([tc(1), tc(2)], needs_auth=True)
    assert cases[0].status_ai == "Blocked" and "RuntimeError: elemen hilang" in cases[0].actual
    assert cases[1].status_ai == "Pass"
    assert None in driver.sessions  # driver dipulihkan dengan sesi baru


def test_llm_unavailable_saves_progress_and_raises(tmp_path):
    runner, _, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS, "TC-PEN-002": LLMUnavailable("endpoint mati")})
    with pytest.raises(LLMUnavailable):
        runner.execute([tc(1), tc(2)], needs_auth=True)
    assert [c.status_ai for c in store.read_testcases()] == ["Pass", None]


def test_login_failed_raises(tmp_path):
    runner, loop, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS}, auth=StubAuth(fail=True))
    with pytest.raises(LoginFailed):
        runner.execute([tc(1)], needs_auth=True)
    assert loop.calls == [] and store.read_testcases()[0].status_ai is None


def test_stop_flag(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-001": PASS}, should_stop=lambda: True)
    runner.execute([tc(1)], needs_auth=True)
    assert loop.calls == []


def test_interrupted_outcome_leaves_case_pending(tmp_path):
    outcomes = {"TC-PEN-001": LoopOutcome(final="blocked", error_kind="interrupted"), "TC-PEN-002": PASS}
    runner, loop, _, _, _ = make(tmp_path, outcomes)
    cases = runner.execute([tc(1), tc(2)], needs_auth=True)
    assert cases[0].status_ai is None and len(loop.calls) == 1


def test_old_steps_dropped_before_rerun(tmp_path):
    runner, _, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS})
    store.append_step(StepRecord(tc_id="TC-PEN-001", step_no=1, timestamp="t", action="click"))
    store.append_step(StepRecord(tc_id="LOGIN-1", step_no=1, timestamp="t", action="click"))
    runner.execute([tc(1)], needs_auth=True)
    assert [s.tc_id for s in store.read_steps()] == ["LOGIN-1"]


# ---------------------------------------------------------------- jeda & logout (bug run Android)
import threading
import time

from qa_agent.agent.control import RunControl
from tests.fakes import el as _el

LOGIN = screen("login", _el(1, "textbox", "Email"), _el(2, "textbox", "Password", input_type="password"),
               _el(3, "button", "Masuk"))


def test_pause_holds_before_next_case(tmp_path):
    control = RunControl()
    runner, loop, _, driver, _ = make(tmp_path, {"TC-PEN-001": PASS, "TC-PEN-002": PASS}, control=control)
    control.pause()
    t = threading.Thread(target=lambda: runner.execute([tc(1), tc(2)], needs_auth=False))
    t.start()
    time.sleep(0.4)
    assert loop.calls == [] and driver.sessions == []  # tidak ada persiapan/eksekusi selama dijeda
    control.resume()
    t.join(5)
    assert [c[0] for c in loop.calls] == ["TC-PEN-001", "TC-PEN-002"]


def test_stop_while_paused_between_cases(tmp_path):
    control = RunControl()
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-001": PASS}, control=control)
    control.pause()
    t = threading.Thread(target=lambda: runner.execute([tc(1)], needs_auth=False))
    t.start()
    time.sleep(0.2)
    control.stop()
    t.join(5)
    assert loop.calls == []


class LogoutLoop(StubLoop):
    """Agent logout: memindahkan driver ke layar login."""

    def __init__(self, outcomes, driver, works=True):
        super().__init__(outcomes)
        self.driver, self.works = driver, works

    def run(self, tc_id, goal, *, allow_logout=False, login=False):
        if tc_id.startswith("LOGOUT"):
            self.calls.append((tc_id, allow_logout))
            if self.works:
                self.driver.current = url("login")
                return PASS
            return LoopOutcome(final="blocked", reason="tombol logout tidak ketemu")
        return super().run(tc_id, goal, allow_logout=allow_logout, login=login)


def make_android(tmp_path, outcomes, works=True):
    from tests.fakes import FakeDriver

    store = RunStore(tmp_path / "run")
    driver = FakeDriver([HOME, LOGIN], url("home"))
    driver.keeps_login = True  # Android: sesi login tetap tersimpan saat aplikasi dibuka ulang
    driver.new_session = lambda auth_state=None: driver.sessions.append(auth_state)  # tetap di layar terakhir
    loop = LogoutLoop(outcomes, driver, works)
    runner = DeepRunner(driver=driver, loop=loop, auth=StubAuth(), store=store)
    return runner, loop, driver


def login_case(n, **kw):
    return QaTestCase(id=f"TC-AUT-00{n}", module="Autentikasi", title=f"Login {n}", expected="ok",
                      start_url=url("login"), **kw)


def test_android_public_case_logs_out_first(tmp_path):
    runner, loop, driver = make_android(tmp_path, {"TC-AUT-001": PASS, "TC-AUT-002": PASS})
    cases = runner.execute([login_case(1), login_case(2)], needs_auth=False)
    assert [c.status_ai for c in cases] == ["Pass", "Pass"]
    logouts = [c for c in loop.calls if c[0].startswith("LOGOUT")]
    assert logouts and all(allow for _, allow in logouts)  # logout diizinkan guard
    assert driver.current == url("login")


def test_android_logout_failure_lets_agent_try_with_explanation(tmp_path):
    blocked = LoopOutcome(final="blocked", reason="tombol logout tidak ada")
    runner, loop, _ = make_android(tmp_path, {"TC-AUT-001": blocked}, works=False)
    goals = []
    original = loop.run
    loop.run = lambda tc_id, goal, **kw: (goals.append((tc_id, goal)), original(tc_id, goal, **kw))[1]
    cases = runner.execute([login_case(1)], needs_auth=False)
    goal = dict(goals)["TC-AUT-001"]
    assert "tidak bisa dibuka otomatis" in goal and "logout" in goal.lower()  # agent tahu masalahnya & bisa diarahkan QA
    assert cases[0].status_ai == "Blocked" and cases[0].actual == "tombol logout tidak ada"


def test_unreachable_start_lets_agent_try_then_skips_same_start_quickly(tmp_path):
    from qa_agent.agent.control import RunControl

    control = RunControl()
    blocked = LoopOutcome(final="blocked", reason="Form Reason Lembur tidak muncul")
    runner, loop, _, driver, _ = make(tmp_path, {"TC-PEN-001": blocked, "TC-PEN-002": PASS, "TC-PEN-003": PASS},
                                      control=control)
    a, b = tc(1), tc(2)
    a.start_url = b.start_url = url("lembur")  # layar kondisional yang tidak tercatat di driver
    cases = runner.execute([a, b], needs_auth=False)
    assert [c[0] for c in loop.calls] == ["TC-PEN-001"]  # TC-002 tidak menghabiskan waktu AI lagi
    assert cases[1].status_ai == "Blocked" and "TC-PEN-001" in cases[1].actual
    # dengan arahan QA tertunda, test case berikutnya tetap dicoba agent
    c = tc(3)
    c.start_url = url("lembur")
    control.hint("buka menu Lembur di menu samping")
    runner.execute([c], needs_auth=False)
    assert loop.calls[-1][0] == "TC-PEN-003"


def test_case_with_logged_in_precondition_uses_auth(tmp_path):
    runner, loop, _, _, auth = make(tmp_path, {"TC-PEN-001": PASS})
    runner.execute([tc(1, precondition="User sudah login sebagai admin")], needs_auth=False)
    assert auth.started == [url("home")]

def test_case_starting_on_public_screen_runs_logged_out_even_if_module_needs_auth(tmp_path):
    """Modul Autentikasi berisi Sign In (publik) dan Form Reason (perlu login)."""
    runner, loop, _, driver, auth = make(tmp_path, {"TC-PEN-001": PASS, "TC-PEN-002": PASS})
    signin = tc(1)
    form = tc(2)
    form.start_url = url("users")
    driver.screens[url("users")] = HOME.model_copy(update={"location": url("users")})
    runner.execute([signin, form], needs_auth=True, public_starts={url("home")})
    assert driver.sessions == [None]  # Sign In: sesi bersih, tanpa login
    assert auth.started == [url("users")]  # Form Reason: login dulu

def test_public_start_case_disables_auto_relogin(tmp_path):
    runner, loop, _, _, auth = make(tmp_path, {"TC-PEN-001": PASS})
    seen = []
    original = loop.run
    loop.run = lambda tc_id, goal, **kw: (seen.append(loop.relogin), original(tc_id, goal, **kw))[1]
    runner.execute([tc(1)], needs_auth=True, public_starts={url("home")})
    assert seen == [None]

def test_negative_credential_goal_warns_against_real_password():
    from qa_agent.orchestrator.deep import goal_for

    wrong = QaTestCase(id="TC-AUT-002", module="Autentikasi", title="Sign In gagal dengan password salah", expected="ditolak")
    assert "kredensial yang BENAR" in goal_for(wrong)
    ok = QaTestCase(id="TC-AUT-001", module="Autentikasi", title="Sign In sukses dengan kredensial valid", expected="masuk")
    assert "kredensial yang BENAR" not in goal_for(ok)

def test_error_during_auto_login_becomes_finding(tmp_path):
    """Popup error saat login otomatis (persiapan) tidak dibuang: test case jadi Perlu Review dengan catatan."""
    runner, loop, _, _, auth = make(tmp_path, {"TC-PEN-001": PASS})
    sig = Signal(kind="ui_error", message="Pesan muncul sesaat lalu hilang: Terjadi kesalahan server")
    original = auth.start_authenticated

    def start(target):
        loop.last_signals = [sig]  # sinyal dari loop LOGIN
        original(target)

    auth.start_authenticated = start
    cases = runner.execute([tc(1)], needs_auth=True)
    assert cases[0].status_ai == "Perlu Review"
    assert "Terjadi kesalahan server" in cases[0].ai_note and "login/logout otomatis" in cases[0].ai_note

def test_valid_credential_goal_uses_saved_account():
    from qa_agent.orchestrator.deep import goal_for

    ok = QaTestCase(id="TC-AUT-001", module="Autentikasi", title="Sign In sukses dengan kredensial valid",
                    test_data="Username: teknisi01, Password: Valid#123", expected="masuk")
    goal = goal_for(ok)
    assert "akun test yang tersimpan" in goal and "{{username}}" in goal
    other = QaTestCase(id="TC-PEN-001", module="Pengguna", title="Tambah pengguna", expected="tersimpan")
    assert "akun test yang tersimpan" not in goal_for(other)

def test_valid_login_test_data_replaced_but_negative_kept():
    from qa_agent.orchestrator.deep import valid_login_test_data

    assert valid_login_test_data("Sign In sukses dengan kredensial valid", "Username: teknisi01, Password: Valid#123", []) \
        == "Akun test tersimpan: username {{username}}, password {{password}}"
    assert valid_login_test_data("Sign In gagal password salah", "Username: teknisi01, Password: Salah#999", []) \
        == "Username: teknisi01, Password: Salah#999"
    assert valid_login_test_data("Sign In dengan field kosong", "Username: (kosong), Password: (kosong)", []) \
        == "Username: (kosong), Password: (kosong)"
    assert valid_login_test_data("Tambah pengguna", "Nama: QA-AUTO Budi", []) == "Nama: QA-AUTO Budi"