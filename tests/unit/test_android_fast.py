"""Jalur cepat Android (uiautomator2): saring jendela sistem, cadangan ke adb biasa bila gagal."""
from qa_agent.drivers.adb import Adb
from qa_agent.drivers.u2fast import strip_system_windows

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" package="com.android.systemui" text="11:41" class="android.widget.TextView" bounds="[0,0][100,60]" />
  <node index="0" package="com.biznet.wfm.dev" text="Work Order" class="android.widget.TextView" bounds="[0,100][500,200]" />
  <node index="0" package="com.google.android.inputmethod.latin" text="q" class="android.widget.Button" bounds="[0,1800][100,1900]" />
  <node index="0" package="com.google.android.permissioncontroller" text="Izinkan" class="android.widget.Button" bounds="[0,900][500,1000]" />
</hierarchy>"""


def test_strip_system_windows_keeps_app_and_permission_dialog():
    out = strip_system_windows(XML)
    assert "Work Order" in out and "Izinkan" in out
    assert "11:41" not in out and 'text="q"' not in out


class FakeFast:
    def __init__(self, results):
        self.results = list(results)
        self.failures = 0
        self.stopped = 0

    def dump(self):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def stop(self):
        self.stopped += 1


def make(results):
    calls = []

    def run(args, timeout):
        calls.append(args)
        if "uiautomator" in " ".join(args):
            return 0, b"UI hierchary dumped to: /sdcard/qa_agent_ui.xml", b""
        return 0, b"<hierarchy><node text='adb biasa' /></hierarchy>", b""

    a = Adb(serial="X", adb_path="adb", run=run)
    a._fast = FakeFast(results)
    return a, calls


def test_fast_dump_used_without_adb_calls():
    a, calls = make(["<hierarchy><node text='cepat' /></hierarchy>"])
    assert "cepat" in a.dump_ui() and calls == [] and a.fast_active


def test_fast_failure_falls_back_to_adb_and_disables_after_repeats():
    a, calls = make([RuntimeError("putus")] * 3)
    fast = a._fast
    for _ in range(3):
        assert "adb biasa" in a.dump_ui()  # tetap dapat hasil dari adb biasa
    assert fast.stopped == 3  # UiAutomator uiautomator2 dimatikan agar dump biasa tidak bentrok
    assert not a.fast_active  # setelah gagal berulang: pakai adb biasa


def test_focus_and_pid_single_command():
    out = (b"  mCurrentFocus=Window{5da u0 com.biznet.wfm.dev/.MainActivity}\n@@QA@@\n4321\n")
    a = Adb(serial="X", adb_path="adb", run=lambda args, t: (0, out, b""))
    assert a.focus_and_pid("com.biznet.wfm.dev") == ("com.biznet.wfm.dev", "com.biznet.wfm.dev.MainActivity", "4321")
    gone = Adb(serial="X", adb_path="adb", run=lambda args, t: (0, b"mCurrentFocus=null\n@@QA@@\n", b""))
    assert gone.focus_and_pid("p") == ("", "", None)
