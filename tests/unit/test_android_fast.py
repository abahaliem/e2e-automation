"""Jalur cepat Android (uiautomator2): saring jendela sistem, cadangan ke adb biasa bila gagal."""
from qa_agent.drivers.adb import Adb
from qa_agent.models import Action
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


def _nav_device(users_has_menu: bool):
    from qa_agent.drivers.android import AndroidDriver
    from tests.android_fakes import HOME_XML, FakeAdb, hierarchy
    from tests.android_fakes import node as n

    reports = hierarchy(n("android.widget.TextView", text="Daftar Laporan", bounds="[0,100][1080,200]", clickable=False))
    users_nodes = [n("android.widget.TextView", text="Daftar Pengguna", bounds="[0,100][1080,200]", clickable=False),
                   n("android.widget.ImageButton", desc="Tambah pengguna", rid="com.demo.app:id/fab",
                     bounds="[900,2100][1040,2240]")]
    if users_has_menu:  # menu samping yang tampil di semua layar
        users_nodes.append(n("android.widget.TextView", text="Laporan", rid="com.demo.app:id/menu_reports",
                             bounds="[0,1500][1080,1600]"))
    adb = FakeAdb({"HOME": HOME_XML, "USERS": hierarchy(*users_nodes), "REPORTS": reports}, "HOME", {
        ("HOME", (0, 300, 1080, 420)): "USERS", ("HOME", (0, 440, 1080, 560)): "REPORTS",
        ("USERS", (0, 1500, 1080, 1600)): "REPORTS"})
    d = AndroidDriver(adb, "com.demo.app", sleep=lambda s: None)
    d.start()
    d.new_session(None)
    home = d.observe()
    d.execute(Action(action="click", element=3), next(e for e in home.elements if e.name == "Laporan"))
    reports_loc = d.observe().location
    d.execute(Action(action="back"), None)
    home = d.observe()
    d.execute(Action(action="click", element=2), next(e for e in home.elements if e.name == "Pengguna"))
    d.observe()
    adb.calls.clear()
    return d, adb, reports_loc


def test_goto_other_menu_via_back_without_reopening_app():
    d, adb, reports_loc = _nav_device(users_has_menu=False)
    d.goto(reports_loc)
    assert d.current_url == reports_loc
    assert not any(c[0] in ("force_stop", "launch") for c in adb.calls)  # aplikasi tidak ditutup-buka
    assert ("key", 4) in adb.calls  # cukup tombol Back lalu tap menu


def test_goto_uses_menu_visible_on_current_screen():
    d, adb, reports_loc = _nav_device(users_has_menu=True)
    d.goto(reports_loc)
    assert d.current_url == reports_loc
    assert not any(c[0] in ("force_stop", "launch", "key") for c in adb.calls)  # langsung tap menu samping


def test_focus_and_pid_single_command():
    out = (b"  mCurrentFocus=Window{5da u0 com.biznet.wfm.dev/.MainActivity}\n@@QA@@\n4321\n")
    a = Adb(serial="X", adb_path="adb", run=lambda args, t: (0, out, b""))
    assert a.focus_and_pid("com.biznet.wfm.dev") == ("com.biznet.wfm.dev", "com.biznet.wfm.dev.MainActivity", "4321")
    gone = Adb(serial="X", adb_path="adb", run=lambda args, t: (0, b"mCurrentFocus=null\n@@QA@@\n", b""))
    assert gone.focus_and_pid("p") == ("", "", None)
