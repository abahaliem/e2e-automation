"""adb tiruan untuk unit test Android (tanpa HP sungguhan)."""
from __future__ import annotations

from typing import Callable

from qa_agent.imaging import solid_png

PNG = solid_png((240, 240, 240), (108, 240))


def node(cls, *, text="", desc="", rid="", bounds="[0,0][100,50]", clickable=True, password=False, enabled=True,
         children="", focusable=None, checkable=False, checked=False, scrollable=False, pkg="com.demo.app"):
    focus = clickable if focusable is None else focusable
    return (f'<node index="0" text="{text}" resource-id="{rid}" class="{cls}" package="{pkg}" content-desc="{desc}" '
            f'checkable="{str(checkable).lower()}" checked="{str(checked).lower()}" clickable="{str(clickable).lower()}" '
            f'enabled="{str(enabled).lower()}" focusable="{str(focus).lower()}" focused="false" '
            f'scrollable="{str(scrollable).lower()}" long-clickable="false" password="{str(password).lower()}" '
            f'selected="false" bounds="{bounds}">{children}</node>')


def hierarchy(*nodes: str) -> str:
    inner = "".join(nodes)
    return ("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\">"
            + node("android.widget.FrameLayout", bounds="[0,0][1080,2400]", clickable=False, children=inner)
            + "</hierarchy>")


LOGIN_XML = hierarchy(
    node("android.widget.TextView", text="Masuk ke Demo", bounds="[100,200][980,280]", clickable=False),
    node("android.widget.EditText", text="Email", rid="com.demo.app:id/email", bounds="[100,400][980,520]"),
    node("android.widget.EditText", text="", rid="com.demo.app:id/password", bounds="[100,560][980,680]", password=True),
    node("android.widget.Button", text="MASUK", rid="com.demo.app:id/login", bounds="[100,760][980,880]"),
)
HOME_XML = hierarchy(
    node("android.widget.TextView", text="Beranda", bounds="[0,100][1080,200]", clickable=False),
    node("android.widget.TextView", text="Pengguna", rid="com.demo.app:id/menu_users", bounds="[0,300][1080,420]"),
    node("android.widget.TextView", text="Laporan", rid="com.demo.app:id/menu_reports", bounds="[0,440][1080,560]"),
)
USERS_XML = hierarchy(
    node("android.widget.TextView", text="Daftar Pengguna", bounds="[0,100][1080,200]", clickable=False),
    node("android.widget.ImageButton", desc="Tambah pengguna", rid="com.demo.app:id/fab", bounds="[900,2100][1040,2240]"),
)


class FakeAdb:
    """Meniru `Adb` tingkat tinggi: layar terskrip + transisi saat tap."""

    def __init__(self, screens: dict[str, str], start: str, transitions: dict | None = None,
                 activity: str = "com.demo.app/.MainActivity", package: str = "com.demo.app") -> None:
        self.screens = screens
        self.current = start
        self.start = start
        self.transitions = transitions or {}
        self.activity = activity
        self.package = package
        self.calls: list[tuple] = []
        self.running = True
        self.crash_text = ""
        self.screencaps = 0
        self.on_tap: Callable[[int, int], None] | None = None

    # --- perangkat ---
    def screen_size(self):
        return (1080, 2400)

    def launch(self, pkg):
        self.calls.append(("launch", pkg))
        self.current = self.start
        self.running = True

    def force_stop(self, pkg):
        self.calls.append(("force_stop", pkg))
        self.running = False

    def current_activity(self):
        return tuple(self.activity.split("/", 1)) if self.running else ("com.android.launcher", ".Launcher")

    def pidof(self, pkg):
        return "1234" if self.running else None

    def crash_log(self, pkg):
        return self.crash_text

    def clear_crash_log(self):
        self.calls.append(("clear_crash_log",))

    def dump_ui(self):
        return self.screens[self.current]

    def screencap(self):
        self.screencaps += 1
        return PNG

    # --- input ---
    def tap(self, x, y):
        self.calls.append(("tap", x, y))
        if self.on_tap:
            self.on_tap(x, y)
        for (screen, (x1, y1, x2, y2)), nxt in self.transitions.items():
            if screen == self.current and x1 <= x <= x2 and y1 <= y <= y2:
                if nxt == "CRASH":
                    self.running = False
                    self.crash_text = "FATAL EXCEPTION: main\nProcess: com.demo.app\njava.lang.NullPointerException"
                else:
                    self.current = nxt
                return

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.calls.append(("swipe", x1, y1, x2, y2))

    def text(self, value):
        self.calls.append(("text", value))

    def keyevent(self, code):
        self.calls.append(("key", code))
        if code == 4 and self.current != self.start:
            self.current = self.start
