import time

import pytest

from qa_agent.drivers.adb import AdbError
from qa_agent.drivers.android import AndroidDriver
from qa_agent.models import Action
from tests.android_fakes import HOME_XML, LOGIN_XML, USERS_XML, FakeAdb, hierarchy, node

MASUK = ("LOGIN", (100, 760, 980, 880))
PENGGUNA = ("HOME", (0, 300, 1080, 420))


def make(**kw):
    adb = FakeAdb({"LOGIN": LOGIN_XML, "HOME": HOME_XML, "USERS": USERS_XML}, "LOGIN",
                  {MASUK: "HOME", PENGGUNA: "USERS"}, **kw)
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    return d, adb


def find(obs, name):
    return next(e for e in obs.elements if e.name == name)


def test_observe_login_screen():
    d, _ = make()
    obs = d.observe()
    assert obs.location.startswith("android://com.demo.app/MainActivity#")
    assert obs.is_login_screen
    assert find(obs, "MASUK").role == "button"
    assert obs.screenshot_annotated.startswith(b"\x89PNG")
    assert d.viewport_size() == {"width": 1080, "height": 2400}


def test_type_resolves_credentials_only_into_password_field():
    d, adb = make()
    d.set_credentials("qa@demo.local", "rahasia 1")
    obs = d.observe()
    assert d.execute(Action(action="type", element=1, value="{{username}}"), find(obs, "Email")).ok
    assert d.execute(Action(action="type", element=2, value="{{password}}"), find(obs, "Password")).ok
    assert d.execute(Action(action="type", element=1, value="{{password}}"), find(obs, "Email")).ok
    typed = [c[1] for c in adb.calls if c[0] == "text"]
    assert typed == ["qa@demo.local", "rahasia 1", "{{password}}"]
    assert any(c == ("key", 67) for c in adb.calls)  # field dikosongkan dulu


def test_click_navigation_records_replayable_path():
    d, adb = make()
    obs = d.observe()
    assert d.execute(Action(action="click", element=4), find(obs, "MASUK")).ok
    home = d.observe()
    assert d.path_to(home.location) == [{"role": "button", "name": "MASUK", "selector": "com.demo.app:id/login"}]
    assert d.execute(Action(action="click", element=2), find(home, "Pengguna")).ok
    users = d.observe()
    assert [s["name"] for s in d.path_to(users.location)] == ["MASUK", "Pengguna"]
    assert d.current_url == users.location

    # sesi baru (aplikasi menyimpan login, jadi terbuka di Beranda), lalu ke layar Pengguna lewat jalur tercatat
    adb.start = "HOME"
    d.new_session(None)
    assert adb.current == "HOME"
    d.goto(users.location)
    assert adb.current == "USERS"
    d.goto(home.location)
    assert adb.current == "HOME"


def test_registered_paths_used_by_new_driver():
    d, _ = make()
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    home = d.observe()
    paths = {home.location: d.path_to(home.location)}

    d2, adb2 = make()
    adb2.start = "HOME"  # sudah login
    d2.register_paths(paths)
    d2.goto(home.location)
    assert adb2.current == "HOME"


def test_goto_unreachable_raises():
    adb = FakeAdb({"HOME": HOME_XML}, "HOME")
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.register_paths({"android://com.demo.app/MainActivity#deadbeef": [{"role": "button", "name": "Tidak ada", "selector": ""}]})
    with pytest.raises(RuntimeError, match="tidak bisa dicapai"):
        d.goto("android://com.demo.app/MainActivity#deadbeef")


def test_start_location_relaunches():
    d, adb = make()
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    d.goto("android://com.demo.app")
    assert adb.current == "LOGIN"


def test_crash_detected_as_signal():
    adb = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML}, "HOME", {PENGGUNA: "CRASH"})
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    obs = d.observe()
    d.execute(Action(action="click", element=2), find(obs, "Pengguna"))
    after = d.observe()
    crash = [s for s in after.signals if s.kind == "page_error"]
    assert crash and "tertutup" in crash[0].message and "NullPointerException" in crash[0].message
    assert not [s for s in d.observe().signals if s.kind == "page_error"]  # dilaporkan sekali


def test_anr_dialog_detected():
    xml = hierarchy(node("android.widget.TextView", text="Demo isn't responding", clickable=False),
                    node("android.widget.Button", text="Wait"))
    adb = FakeAdb({"S": xml}, "S")
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    sig = [s for s in d.observe().signals if s.kind == "page_error"]
    assert sig and "isn't responding" in sig[0].message


def test_scroll_back_wait():
    d, adb = make()
    assert d.execute(Action(action="scroll", value="down"), None).ok
    swipe = [c for c in adb.calls if c[0] == "swipe"][-1]
    assert swipe[2] > swipe[4]  # jari bergerak ke atas untuk menggulir ke bawah
    assert d.execute(Action(action="back"), None).ok
    assert ("key", 4) in adb.calls
    assert d.execute(Action(action="wait", value="0"), None).ok


def test_manual_input():
    d, adb = make()
    assert d.manual_input({"kind": "click", "x": 0.5, "y": 0.5}).ok
    assert ("tap", 540.0, 1200.0) in adb.calls
    assert d.manual_input({"kind": "key", "key": "Enter"}).ok and ("key", 66) in adb.calls
    assert d.manual_input({"kind": "key", "key": "Escape"}).ok and ("key", 4) in adb.calls
    assert d.manual_input({"kind": "type", "text": "halo"}).ok and ("text", "halo") in adb.calls
    assert d.manual_input({"kind": "scroll", "dy": 300}).ok
    assert not d.manual_input({"kind": "terbang"}).ok


def test_non_ascii_text_reported_not_crash():
    class StrictAdb(FakeAdb):
        def text(self, value):
            raise ValueError("adb input text tidak mendukung karakter ini")

    adb = StrictAdb({"LOGIN": LOGIN_XML}, "LOGIN")
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    obs = d.observe()
    result = d.execute(Action(action="type", element=1, value="café"), find(obs, "Email"))
    assert not result.ok and not result.fatal and "tidak mendukung" in result.error


def test_device_disconnected_is_fatal():
    class Gone(FakeAdb):
        def tap(self, x, y):
            raise AdbError("error: device 'R58M123' not found")

    adb = Gone({"LOGIN": LOGIN_XML}, "LOGIN")
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    obs = d.observe()
    result = d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    assert result.fatal and "not found" in result.error


def test_live_frames_only_while_streaming():
    adb = FakeAdb({"LOGIN": LOGIN_XML}, "LOGIN")
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None, frame_interval=0.05)
    d.start()
    frames = []
    d.set_frame_sink(lambda jpeg, meta: frames.append((jpeg, meta)))
    time.sleep(0.2)
    assert frames == []
    d.set_streaming(True)
    deadline = time.time() + 2
    while len(frames) < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert len(frames) >= 2
    jpeg, meta = frames[-1]
    assert jpeg[:2] == b"\xff\xd8" and meta == {"width": 1080, "height": 2400}
    d.set_streaming(False)
    time.sleep(0.2)
    count = len(frames)
    time.sleep(0.3)
    assert len(frames) == count
    d.stop()


def test_replay_skips_login_steps_when_already_logged_in():
    # Jalur dari explore: LOGIN -(MASUK)-> HOME -(Pengguna)-> USERS. Aplikasi yang sudah login langsung membuka HOME.
    d, adb = make()
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    home = d.observe()
    d.execute(Action(action="click", element=2), find(home, "Pengguna"))
    users = d.observe()
    paths = {users.location: d.path_to(users.location)}

    adb2 = FakeAdb({"LOGIN": LOGIN_XML, "HOME": HOME_XML, "USERS": USERS_XML}, "HOME", {PENGGUNA: "USERS"})
    d2 = AndroidDriver(adb2, "com.demo.app", sleep=lambda s: None)
    d2.start()
    d2.register_paths(paths)
    d2.goto(users.location)
    assert adb2.current == "USERS"


def test_replay_stops_at_login_screen_for_auth_to_handle():
    d, adb = make()
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    home = d.observe()
    d.new_session(None)  # aplikasi kembali ke LOGIN (sesi habis)
    d.goto(home.location)  # tidak menekan MASUK dengan form kosong
    assert adb.current == "LOGIN"
    assert not [c for c in adb.calls[-3:] if c[0] == "tap"]


def test_typing_empty_credential_is_reported():
    d, adb = make()
    d.set_credentials("", "")
    obs = d.observe()
    result = d.execute(Action(action="type", element=1, value="{{username}}"), find(obs, "Email"))
    assert not result.ok and not result.fatal and "akun test" in result.error.lower()
    assert not [c for c in adb.calls if c[0] == "text"]


# ---------------------------------------------------------------- splash, logout, layar live
SPLASH_XML = hierarchy()  # splash/loading: belum ada elemen


def test_new_session_waits_until_splash_finished():
    adb = FakeAdb({"SPLASH": SPLASH_XML, "LOGIN": LOGIN_XML}, "SPLASH")
    dumps = {"n": 0}
    original = adb.dump_ui

    def dump():
        dumps["n"] += 1
        if dumps["n"] >= 3:
            adb.current = "LOGIN"  # splash selesai setelah beberapa saat
        return original()

    adb.dump_ui = dump
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    assert d.observe().is_login_screen


def test_keeps_login_and_records_replayable_steps():
    d, adb = make()
    assert d.keeps_login is True
    d.start_recording()
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    home = d.observe()
    d.execute(Action(action="click", element=2), find(home, "Pengguna"))
    steps = d.stop_recording()
    assert [s["name"] for s in steps] == ["MASUK", "Pengguna"]
    assert d.stop_recording() == []
    d.new_session(None)
    assert d.replay_steps(steps) is True and adb.current == "USERS"
    d.new_session(None)
    assert d.replay_steps([{"role": "button", "name": "Tidak ada", "selector": ""}]) is False


def test_live_frames_use_parallel_capture():
    d, adb = make()
    frames = []
    d.set_frame_sink(lambda jpeg, meta: frames.append(meta))
    d.set_streaming(True)
    time.sleep(0.5)
    d.set_streaming(False)
    assert len(frames) >= 3 and d.frame_workers >= 2

def test_transient_error_popup_after_tap_is_reported():
    """Popup/snackbar error yang muncul sesaat setelah tap lalu hilang tetap tercatat sebagai sinyal."""
    popup = hierarchy(
        node("android.widget.TextView", text="Beranda", bounds="[0,100][1080,200]", clickable=False),
        node("android.widget.TextView", text="Terjadi kesalahan: gagal memuat order", bounds="[0,2000][1080,2100]", clickable=False),
    )
    adb = FakeAdb({"LOGIN": LOGIN_XML, "POPUP": popup, "HOME": HOME_XML}, "LOGIN", {MASUK: "POPUP"})
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    original = adb.dump_ui
    seen = {"n": 0}

    def dump():
        if adb.current == "POPUP":
            seen["n"] += 1
            if seen["n"] > 1:
                adb.current = "HOME"  # popup hilang sendiri
        return original()

    adb.dump_ui = dump
    obs = d.observe()
    d.execute(Action(action="click", element=4), find(obs, "MASUK"))
    after = d.observe()
    assert any(s.kind == "ui_error" and "gagal memuat order" in s.message for s in after.signals)
    assert not any("gagal memuat order" in s.message for s in d.observe().signals)  # dilaporkan sekali