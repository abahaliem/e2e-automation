import pytest

from qa_agent.drivers.adb import Adb, AdbError, AdbNotFound, escape_text, find_adb

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class Runner:
    """Mencatat perintah adb dan mengembalikan respons terskrip berdasarkan potongan argumen."""

    def __init__(self, responses: dict[str, tuple[int, bytes, bytes]] | None = None):
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        joined = " ".join(args)
        for key, resp in self.responses.items():
            if key in joined:
                return resp
        return (0, b"", b"")


def adb(responses=None, serial="R58M123"):
    r = Runner(responses)
    return Adb(serial=serial, adb_path="adb", run=r), r


def test_devices_parsing():
    out = (b"List of devices attached\n"
           b"R58M123   device usb:1-1 product:a54xx model:SM_A546E device:a54x transport_id:3\n"
           b"emulator-5554\tdevice product:sdk_gphone64 model:sdk_gphone64_x86_64 device:emu64x transport_id:1\n"
           b"ZY22ABC unauthorized usb:1-2 transport_id:4\n\n")
    a, _ = adb({"devices -l": (0, out, b"")}, serial=None)
    devices = a.devices()
    assert [(d.serial, d.state, d.model) for d in devices] == [
        ("R58M123", "device", "SM A546E"),
        ("emulator-5554", "device", "sdk gphone64 x86 64"),
        ("ZY22ABC", "unauthorized", ""),
    ]
    assert devices[1].emulator and not devices[0].emulator


def test_serial_passed_to_every_command():
    a, r = adb({"shell": (0, b"14\n", b"")})
    assert a.android_version() == "14"
    assert r.calls[0][:3] == ["adb", "-s", "R58M123"]


def test_error_raises_adberror():
    a, _ = adb({"pm list": (1, b"", b"error: device unauthorized")})
    with pytest.raises(AdbError, match="unauthorized"):
        a.packages()


def test_missing_adb_binary():
    def boom(args, timeout):
        raise FileNotFoundError("adb")

    with pytest.raises(AdbNotFound):
        Adb(adb_path="adb", run=boom).devices()


def test_packages_and_install():
    a, r = adb({"pm list packages -3": (0, b"package:com.b\npackage:com.a\n", b""),
                "install": (0, b"Performing Streamed Install\nSuccess\n", b"")})
    assert a.packages() == ["com.a", "com.b"]
    a.install("C:/apk/demo.apk")
    assert ["install", "-r", "-g", "C:/apk/demo.apk"] == r.calls[-1][3:]
    a2, _ = adb({"install": (0, b"Failure [INSTALL_FAILED_VERSION_DOWNGRADE]\n", b"")})
    with pytest.raises(AdbError, match="VERSION_DOWNGRADE"):
        a2.install("x.apk")


def test_screen_size_prefers_override():
    a, _ = adb({"wm size": (0, b"Physical size: 1080x2400\nOverride size: 720x1600\n", b"")})
    assert a.screen_size() == (720, 1600)
    a2, _ = adb({"wm size": (0, b"Physical size: 1080x2400\n", b"")})
    assert a2.screen_size() == (1080, 2400)


def test_current_activity():
    out = b"  mCurrentFocus=Window{a1b2 u0 com.demo.app/com.demo.app.ui.MainActivity}\n  mFocusedApp=..."
    a, _ = adb({"dumpsys window": (0, out, b"")})
    assert a.current_activity() == ("com.demo.app", "com.demo.app.ui.MainActivity")
    a2, _ = adb({"dumpsys window": (0, b"mCurrentFocus=null\n", b"")})
    assert a2.current_activity() == ("", "")


def test_screencap_and_dump():
    a, r = adb({"screencap": (0, PNG_MAGIC + b"data", b""),
                "uiautomator dump": (0, b"UI hierchary dumped to: /sdcard/qa_agent_ui.xml\n", b""),
                "cat /sdcard/qa_agent_ui.xml": (0, b"<?xml version='1.0'?><hierarchy></hierarchy>", b"")})
    assert a.screencap().startswith(PNG_MAGIC)
    assert "<hierarchy" in a.dump_ui()
    a2, _ = adb({"screencap": (0, b"not png", b"")})
    with pytest.raises(AdbError):
        a2.screencap()
    a3, _ = adb({"uiautomator dump": (0, b"ERROR: could not get idle state.\n", b""), "cat": (0, b"", b"")})
    with pytest.raises(AdbError, match="idle"):
        a3.dump_ui()


def test_input_commands():
    a, r = adb()
    a.tap(10.6, 20.2)
    a.swipe(1, 2, 3, 4, 250)
    a.keyevent(4)
    a.text("budi santoso")
    shells = [c[3:] for c in r.calls]
    assert shells[0] == ["shell", "input", "tap", "11", "20"]
    assert shells[1] == ["shell", "input", "swipe", "1", "2", "3", "4", "250"]
    assert shells[2] == ["shell", "input", "keyevent", "4"]
    assert shells[3] == ["shell", "input", "text", "budi%ssantoso"]


def test_escape_text():
    assert escape_text("a b") == "a%sb"
    assert escape_text("O'Brien") == "O\\'Brien"
    assert escape_text('x&y(z)$') == 'x\\&y\\(z\\)\\$'
    with pytest.raises(ValueError, match="tidak mendukung"):
        escape_text("café")


def test_launch_and_crash_log():
    a, r = adb({"monkey": (0, b"Events injected: 1\n", b""),
                "logcat -b crash -d": (0, b"--------- beginning of crash\nE AndroidRuntime: FATAL EXCEPTION: main\n"
                                          b"E AndroidRuntime: Process: com.demo.app, PID: 9\n"
                                          b"E AndroidRuntime: java.lang.NullPointerException\n", b"")})
    a.launch("com.demo.app")
    assert "monkey -p com.demo.app" in " ".join(r.calls[-1])
    log = a.crash_log("com.demo.app")
    assert "FATAL EXCEPTION" in log and "NullPointerException" in log
    a2, _ = adb({"monkey": (0, b"** No activities found to run, monkey aborted.\n", b"")})
    with pytest.raises(AdbError, match="tidak punya layar pembuka"):
        a2.launch("com.service.only")


def test_find_adb_uses_known_locations(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    sdk = tmp_path / "Sdk" / "platform-tools"
    sdk.mkdir(parents=True)
    (sdk / "adb.exe").write_bytes(b"")
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "Sdk"))
    assert find_adb(extra_dirs=[]) == str(sdk / "adb.exe")
    monkeypatch.delenv("ANDROID_HOME")
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    assert find_adb(extra_dirs=[]) is None
    assert find_adb(extra_dirs=[sdk]) == str(sdk / "adb.exe")


def test_keyevents_in_one_command():
    a, r = adb()
    a.keyevents(123, 67, 67)
    assert r.calls[-1][3:] == ["shell", "input", "keyevent", "123", "67", "67"]
