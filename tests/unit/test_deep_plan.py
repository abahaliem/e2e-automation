import json

import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import AppMap, QaTestCase, ScreenInfo, Signal
from qa_agent.orchestrator.deep import DeepPlanner, PlanError, goal_for, is_logout_case, judge
from tests.fakes import url


def app_map():
    return AppMap(target=url(""), screens=[
        ScreenInfo(fingerprint="a", url=url("users"), module="Pengguna", page_name="Daftar Pengguna"),
        ScreenInfo(fingerprint="b", url=url("users/new"), module="Pengguna", page_name="Tambah Pengguna",
                   forms=[{"name": "Form", "fields": [{"label": "Nama", "type": "text"}]}]),
        ScreenInfo(fingerprint="c", url=url("reports"), module="Laporan", page_name="Laporan"),
    ])


CASE = {"title": "Tambah valid", "page": "Tambah Pengguna", "type": "Positif", "priority": "high",
        "steps": ["Isi form", "Klik Simpan"], "expected": "Tersimpan", "expected_source": "PRD",
        "start_url": "/users/new", "test_data": {"Nama": "QA-AUTO Budi"}}


def planner(replies, max_tcs=15):
    llm = FakeLLM(replies)
    return DeepPlanner(llm, data_prefix="QA-AUTO-X", max_tcs=max_tcs), llm


def test_plan_builds_ids_and_resolves_start():
    reply = {"test_cases": [CASE, {**CASE, "title": "Tanpa expected", "expected": None},
                            {**CASE, "title": "Validasi", "type": "validasi", "start_url": "", "page": "daftar pengguna"}]}
    p, llm = planner([json.dumps(reply)])
    cases = p.plan(app_map(), "Pengguna", prd_text="PRD: email wajib valid")
    assert [c.id for c in cases] == ["TC-PEN-001", "TC-PEN-002"]
    first, second = cases
    assert first.start_url == url("users/new") and first.type == "positif" and first.priority == "High"
    assert first.expected_source == "PRD"
    assert json.loads(first.test_data) == {"Nama": "QA-AUTO Budi"}
    assert second.title == "Validasi" and second.start_url == url("users")
    system, messages = llm.calls[0]
    assert system.startswith("MODE: PLAN") and "## PRD" in messages[0].text


def test_expected_source_forced_to_inference_without_prd():
    p, _ = planner([json.dumps({"test_cases": [CASE]})])
    assert p.plan(app_map(), "Pengguna")[0].expected_source == "Inferensi AI"


def test_module_name_tolerant_and_unknown_lists_modules():
    p, _ = planner([json.dumps({"test_cases": [CASE]})])
    assert p.plan(app_map(), "  pengguna ")[0].module == "Pengguna"
    unknown, _ = planner([])
    with pytest.raises(PlanError, match="Pengguna, Laporan"):
        unknown.plan(app_map(), "Transaksi")


def test_invalid_reply_retried_then_plan_error():
    p, llm = planner(["bukan json", '{"test_cases": "x"}'])
    with pytest.raises(PlanError, match="gagal"):
        p.plan(app_map(), "Pengguna")
    assert len(llm.calls) == 2 and "tidak valid" in llm.calls[1][1][-1].text


def test_max_tcs_truncates():
    p, _ = planner([json.dumps({"test_cases": [CASE] * 5})], max_tcs=3)
    assert len(p.plan(app_map(), "Pengguna")) == 3


def test_steps_string_is_split():
    p, _ = planner([json.dumps({"test_cases": [{**CASE, "steps": "1. Buka\n2. Klik"}]})])
    assert p.plan(app_map(), "Pengguna")[0].steps == ["1. Buka", "2. Klik"]


TC_AI = QaTestCase(id="T", module="M", title="t", expected="e")
TC_PRD = TC_AI.model_copy(update={"expected_source": "PRD"})
SIG500 = Signal(kind="http_error", message="HTTP 500", status=500)


@pytest.mark.parametrize("outcome, tc, expected", [
    (LoopOutcome(final="done", status="pass", signals=[SIG500]), TC_AI, ("Fail", "Major")),
    (LoopOutcome(final="done", status="pass", signals=[Signal(kind="blocked_request", message="x", method="POST", url="u"), SIG500]), TC_AI, ("Skipped", None)),
    (LoopOutcome(final="done", status="pass", signals=[Signal(kind="page_error", message="x")]), TC_AI, ("Fail", "Major")),
    (LoopOutcome(final="done", status="pass", signals=[Signal(kind="http_error", message="x", status=404)]), TC_AI, ("Pass", None)),
    (LoopOutcome(final="done", status="fail", severity="Critical"), TC_PRD, ("Fail", "Critical")),
    (LoopOutcome(final="done", status="fail"), TC_AI, ("Perlu Review", "Minor")),
    (LoopOutcome(final="done", status="pass"), TC_AI, ("Pass", None)),
    (LoopOutcome(final="blocked", error_kind="loop"), TC_AI, ("Blocked", None)),
    (LoopOutcome(final="blocked", guard_blocks=1, error_kind="agent"), TC_AI, ("Skipped", None)),
])
def test_judge(outcome, tc, expected):
    assert judge(outcome, tc) == expected


def test_goal_and_logout_detection():
    tc = QaTestCase(id="TC-AUT-001", module="Autentikasi", title="Logout dari aplikasi", steps=["Klik Keluar"], expected="Kembali ke login")
    goal = goal_for(tc)
    assert goal.startswith("Jalankan test case TC-AUT-001: Logout dari aplikasi\n")
    assert "1. Klik Keluar" in goal and "Expected result: Kembali ke login" in goal
    assert is_logout_case(tc)
    assert not is_logout_case(TC_AI)
