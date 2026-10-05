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
