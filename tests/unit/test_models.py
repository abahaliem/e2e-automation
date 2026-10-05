from qa_agent.models import (
    Action,
    AppMap,
    Element,
    Observation,
    QaTestCase,
    ScreenInfo,
    Signal,
    StepRecord,
)


def screen(module, url, public=False):
    return ScreenInfo(fingerprint=url + "|x", url=url, module=module, page_name=url, public=public)


def test_action_defaults():
    a = Action(action="click", element=2)
    assert a.risk == "low" and a.value is None and a.status is None


def test_observation_login_detection():
    login = Observation(location="http://a/login", elements=[Element(index=1, role="input", name="Password", input_type="password")])
    home = Observation(location="http://a/", elements=[Element(index=1, role="link", name="Home")])
    change_password = Observation(location="http://a/akun", elements=[
        Element(index=1, role="input", name="Password lama", input_type="password"),
        Element(index=2, role="input", name="Password baru", input_type="password"),
    ])
    assert login.is_login_screen is True
    assert home.is_login_screen is False
    assert change_password.is_login_screen is False


def test_app_map_modules_ordered_unique():
    m = AppMap(target="http://a", screens=[screen("Dashboard", "http://a/"), screen("Pengguna", "http://a/users"), screen("Pengguna", "http://a/users/new")])
    assert m.modules() == ["Dashboard", "Pengguna"]


def test_app_map_find_module_case_and_whitespace():
    m = AppMap(target="http://a", screens=[screen("Pengguna", "http://a/users")])
    assert m.find_module("  pengguna ") == "Pengguna"
    assert m.find_module("Laporan") is None
    assert [s.url for s in m.screens_for(" PENGGUNA")] == ["http://a/users"]
    assert m.screens_for("Laporan") == []


def test_testcase_effective_status():
    tc = QaTestCase(id="TC-1", module="M", title="T", expected="E", status_ai="Perlu Review")
    assert tc.effective_status == "Perlu Review"
    tc.status_final = "Fail"
    assert tc.effective_status == "Fail"


def test_step_record_roundtrip_unicode():
    rec = StepRecord(
        tc_id="TC-1", step_no=1, timestamp="2026-10-05T10:00:00", action="type",
        element={"role": "input", "name": "Nama — Ä", "selector": "#nama"}, value="Budi 😀",
        signals=[Signal(kind="http_error", message="HTTP 500", status=500, url="http://a/x", method="POST")],
    )
    back = StepRecord.model_validate_json(rec.model_dump_json())
    assert back == rec
