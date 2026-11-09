import pytest

from qa_agent.config import Config
from qa_agent.drivers.android import AndroidDriver
from qa_agent.evidence import RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import ScreenInfo
from qa_agent.orchestrator.explore import Explorer
from qa_agent.orchestrator.fingerprint import normalize_location
from qa_agent.agent import prompts
from qa_agent.runtime import build_runtime
from qa_agent.config import Credentials
from tests.android_fakes import HOME_XML, USERS_XML, FakeAdb, hierarchy, node
import json
import re


def android_cfg(**over):
    data = {"target": {"platform": "android", "url": "android://com.demo.app"},
            "accounts": [{"role": "admin", "username_env": "-", "password_env": "-"}],
            "llm": {"base_url": "http://x/v1", "model": "m", "api_key_env": "-"}}
    data.update(over)
    return Config.model_validate(data)


def test_config_android_target():
    cfg = android_cfg()
    assert cfg.target.platform == "android"
    assert cfg.target.package == "com.demo.app"
    assert cfg.domains() == ["com.demo.app"]
    with pytest.raises(Exception):
        Config.model_validate({"target": {"url": "android://com.demo.app"}, "accounts": [{"role": "a", "username_env": "-", "password_env": "-"}],
                               "llm": {"base_url": "http://x/v1", "model": "m", "api_key_env": "-"}})
    with pytest.raises(Exception):
        android_cfg(target={"platform": "android", "url": "http://web.test"})


def test_guard_android_scheme():
    g = Guard("dev", ["com.demo.app"])
    assert g.is_allowed_url("android://com.demo.app/MainActivity#abcd1234")
    assert not g.is_allowed_url("android://com.lain.app/Main#x")


def test_normalize_location_keeps_android_screen_key():
    loc = "android://com.demo.app/MainActivity#abcd1234"
    assert normalize_location(loc) == loc


def test_screeninfo_nav_path_default():
    assert ScreenInfo(fingerprint="f", url="u", module="m", page_name="p").nav_path == []


def test_android_prompt_note():
    text = prompts.execute_system("android", "QA-AUTO")
    assert "aplikasi android" in text and "tombol Kembali" in text
    assert "tombol Kembali" not in prompts.execute_system("web", "QA-AUTO")


REPORTS_XML = hierarchy(node("android.widget.TextView", text="Laporan Bulanan", clickable=False),
                        node("android.widget.Button", text="Unduh", rid="com.demo.app:id/download"))


def explore_brain(system, messages):
    text = messages[0].text
    if system.startswith("MODE: EXPLORE_SCREEN"):
        links = [int(i) for i, name in re.findall(r'^\[(\d+)\] button "(Pengguna|Laporan)"', text, re.M)]
        module = "Pengguna" if "Daftar Pengguna" in text else "Laporan" if "Laporan Bulanan" in text else "Beranda"
        return json.dumps({"module": module, "page_name": module, "purpose": "x", "nav_candidates": links})
    raise AssertionError("tidak diharapkan")


def test_explorer_maps_android_screens_with_replayable_paths(tmp_path):
    adb = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML, "REPORTS": REPORTS_XML}, "HOME",
                  {("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS"})
    driver = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    driver.start()
    store = RunStore(tmp_path / "run")
    explorer = Explorer(driver=driver, llm=FakeLLM(explore_brain), guard=Guard("dev", ["com.demo.app"]), store=store,
                        auth=None, start_url="android://com.demo.app", max_minutes=1)
    app_map = explorer.run()
    assert app_map.modules() == ["Beranda", "Pengguna", "Laporan"]
    users = app_map.screens_for("Pengguna")[0]
    assert [s["name"] for s in users.nav_path] == ["Pengguna"]
    assert app_map.screens_for("Beranda")[0].nav_path == []

    # driver baru (mis. run modul) bisa langsung ke layar Laporan
    adb2 = FakeAdb(adb.screens, "HOME", adb.transitions)
    d2 = AndroidDriver(adb2, "com.demo.app", sleep=lambda s: None)
    d2.start()
    d2.register_paths({s.url: s.nav_path for s in app_map.screens})
    d2.goto(app_map.screens_for("Laporan")[0].url)
    assert adb2.current == "REPORTS"


def test_build_runtime_android(tmp_path):
    rt = build_runtime(android_cfg(), RunStore(tmp_path / "r"), tmp_path, environment="dev", llm=FakeLLM([]),
                       credentials=Credentials(role="admin", username="u", password="p"), device_serial="R58M123")
    assert isinstance(rt.driver, AndroidDriver)
    assert rt.driver.adb.serial == "R58M123" and rt.driver.package == "com.demo.app"
    assert rt.loop.platform == "android"


def test_login_without_account_fails_fast_with_clear_message(tmp_path):
    from qa_agent.orchestrator.auth import LoginFailed

    llm = FakeLLM([])
    rt = build_runtime(android_cfg(), RunStore(tmp_path / "r"), tmp_path, environment="dev", llm=llm,
                       credentials=Credentials(role="default", username="", password=""), device_serial="X")
    with pytest.raises(LoginFailed, match="akun test"):
        rt.auth.login()
    assert llm.calls == []  # AI tidak dipanggil sia-sia


POPUP_XML = hierarchy(
    node("android.widget.TextView", text="Form Reason Lembur", bounds="[0,100][1080,200]", clickable=False),
    node("android.widget.EditText", text="Reason", rid="com.demo.app:id/reason", bounds="[0,300][1080,420]"),
    node("android.widget.Button", text="Submit Reason", rid="com.demo.app:id/submit", bounds="[0,500][1080,600]"),
)


def popup_brain(system, messages):
    text = messages[0].text
    if "Form Reason Lembur" in text:
        return json.dumps({"module": "Lembur", "page_name": "Form Reason Lembur", "purpose": "x", "nav_candidates": []})
    return explore_brain(system, messages)


def test_explorer_dismisses_blocking_popup_with_back_and_maps_screen_behind(tmp_path):
    """Form popup setelah login menutupi halaman utama: explorer menekan Kembali lalu memetakan menu di baliknya."""
    adb = FakeAdb({"POPUP": POPUP_XML, "HOME": HOME_XML, "USERS": USERS_XML, "REPORTS": REPORTS_XML}, "POPUP",
                  {("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS"})

    def keyevent(code):
        adb.calls.append(("key", code))
        if code == 4:
            adb.current = {"POPUP": "HOME", "USERS": "HOME", "REPORTS": "HOME"}.get(adb.current, adb.current)

    adb.keyevent = keyevent
    driver = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    driver.start()
    store = RunStore(tmp_path / "run")
    explorer = Explorer(driver=driver, llm=FakeLLM(popup_brain), guard=Guard("dev", ["com.demo.app"]), store=store,
                        auth=None, start_url="android://com.demo.app", max_minutes=1)
    app_map = explorer.run()
    assert app_map.modules() == ["Lembur", "Beranda", "Pengguna", "Laporan"]
    home = app_map.screens_for("Beranda")[0]
    assert home.nav_path == [{"key": "back"}]
    users = app_map.screens_for("Pengguna")[0]
    assert users.nav_path[0] == {"key": "back"} and users.nav_path[-1]["name"] == "Pengguna"

    # run modul: jalur dengan langkah Kembali bisa diputar ulang dari awal aplikasi
    d2 = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d2.start()
    d2.register_paths({s.url: s.nav_path for s in app_map.screens})
    d2.goto(users.url)
    assert adb.current == "USERS"

def test_explorer_probes_buttons_when_ai_gives_no_nav_candidates(tmp_path):
    """AI tidak menyebut kandidat navigasi (jawaban kosong/gagal dibaca): tombol aman tetap dicoba diklik."""
    adb = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML, "REPORTS": REPORTS_XML}, "HOME",
                  {("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS"})
    driver = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    driver.start()

    def lazy_brain(system, messages):
        data = json.loads(explore_brain(system, messages))
        data["nav_candidates"] = []
        return json.dumps(data)

    explorer = Explorer(driver=driver, llm=FakeLLM(lazy_brain), guard=Guard("dev", ["com.demo.app"]),
                        store=RunStore(tmp_path / "run"), auth=None, start_url="android://com.demo.app", max_minutes=1)
    app_map = explorer.run()
    assert set(app_map.modules()) == {"Beranda", "Pengguna", "Laporan"}
    assert not any(c == ("key", 4) for c in adb.calls[:3])  # menu ditemukan, tidak perlu menekan Kembali

def test_explorer_asks_before_finishing_and_continues_on_request(tmp_path):
    """Setelah layar habis, explorer bertanya. Lanjutkan → tombol yang belum dicoba ikut dipetakan. Selesai → berhenti."""
    import threading
    import time

    from qa_agent.agent.control import RunControl

    adb = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML, "REPORTS": REPORTS_XML}, "HOME",
                  {("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS"})
    driver = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    driver.start()
    control = RunControl()
    events: list[dict] = []
    explorer = Explorer(driver=driver, llm=FakeLLM(explore_brain), guard=Guard("dev", ["com.demo.app"]),
                        store=RunStore(tmp_path / "run"), auth=None, start_url="android://com.demo.app", max_minutes=1,
                        control=control, on_event=events.append, ask_to_continue=True, probe_limit=1)
    result: dict = {}
    t = threading.Thread(target=lambda: result.setdefault("map", explorer.run()))
    t.start()

    def wait_ask(n):
        deadline = time.time() + 10
        while time.time() < deadline:
            if sum(1 for e in events if e["type"] == "explore.ask") >= n and control.state == "paused":
                return next(e for e in reversed(events) if e["type"] == "explore.ask")
            time.sleep(0.05)
        raise AssertionError("explorer tidak bertanya")

    first = wait_ask(1)
    assert first["screens"] == 2 and t.is_alive()  # Beranda + Pengguna (hanya 1 tombol dicoba)
    control.resume()  # Lanjutkan memetakan
    second = wait_ask(2)
    assert second["screens"] == 3 and second["new_screens"] == 1  # Laporan ditemukan di putaran lanjutan
    control.finish_explore()  # Selesai
    t.join(10)
    assert not t.is_alive()
    assert result["map"].modules() == ["Beranda", "Pengguna", "Laporan"]


def test_explorer_without_ask_finishes_directly(tmp_path):
    adb = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML, "REPORTS": REPORTS_XML}, "HOME",
                  {("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS"})
    driver = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    driver.start()
    from qa_agent.agent.control import RunControl

    events: list[dict] = []
    explorer = Explorer(driver=driver, llm=FakeLLM(explore_brain), guard=Guard("dev", ["com.demo.app"]),
                        store=RunStore(tmp_path / "run"), auth=None, start_url="android://com.demo.app", max_minutes=1,
                        control=RunControl(), on_event=events.append)
    explorer.run()
    assert not any(e["type"] == "explore.ask" for e in events)