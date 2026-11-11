"""Pembungkus `adb` (Android Debug Bridge) lewat subprocess. Tidak memasang apa pun di HP."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

Runner = Callable[[list[str], float], tuple[int, bytes, bytes]]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
UI_DUMP_PATH = "/sdcard/qa_agent_ui.xml"
_SHELL_SPECIAL = set("\\'\"`$&|;<>()*~!#?[]{}")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(Exception):
    """Perintah adb gagal."""


class AdbNotFound(AdbError):
    """Program adb (Android platform-tools) tidak ditemukan."""


@dataclass
class DeviceInfo:
    serial: str
    state: str  # device | unauthorized | offline | ...
    model: str = ""
    product: str = ""

    @property
    def emulator(self) -> bool:
        return self.serial.startswith("emulator-")


def _default_run(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
    return proc.returncode, proc.stdout, proc.stderr


def find_adb(extra_dirs: Iterable[Path | str] | None = None) -> str | None:
    """Cari adb: PATH, folder tambahan (mis. folder data QA Agent), lalu lokasi Android SDK yang umum."""
    found = shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if os.name == "nt" else "adb"
    candidates: list[Path] = [Path(d) for d in (extra_dirs or [])]
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]) / "platform-tools")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools")
    for folder in candidates:
        path = folder / exe
        if path.is_file():
            return str(path)
    return None


def escape_text(value: str) -> str:
    """Escape untuk `adb shell input text`: spasi → %s, karakter shell di-backslash. Hanya ASCII."""
    if any(ord(ch) > 126 or (ord(ch) < 32) for ch in value):
        raise ValueError("adb input text tidak mendukung karakter ini (hanya huruf/angka/simbol ASCII)")
    out = []
    for ch in value:
        if ch == " ":
            out.append("%s")
        elif ch in _SHELL_SPECIAL:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


class Adb:
    def __init__(self, serial: str | None = None, adb_path: str | None = None, run: Runner | None = None,
                 fast: bool = False) -> None:
        """`fast`: baca layar & screenshot lewat uiautomator2 (jauh lebih cepat); otomatis kembali ke adb biasa
        bila tidak tersedia atau gagal berulang."""
        self.serial = serial
        self.adb_path = adb_path or find_adb() or "adb"
        self._run = run or _default_run
        self._fast = None
        if fast:
            from qa_agent.drivers import u2fast

            if u2fast.enabled():
                self._fast = u2fast.FastDevice(serial, self.adb_path)

    FAST_MAX_FAILURES = 3

    def _fast_call(self, name: str):
        """Jalankan operasi jalur cepat; None bila tidak aktif / gagal (pemanggil memakai adb biasa)."""
        fast = self._fast
        if fast is None:
            return None
        try:
            result = getattr(fast, name)()
            fast.failures = 0
            return result
        except Exception:  # noqa: BLE001 - jalur cepat hanya pelengkap
            fast.failures += 1
            # UiAutomator milik uiautomator2 dimatikan dulu: kalau masih hidup, `uiautomator dump` biasa ikut gagal.
            # Panggilan cepat berikutnya menyalakannya lagi.
            fast.stop()
            if fast.failures >= self.FAST_MAX_FAILURES:
                self._fast = None  # pakai adb biasa sampai sesi berikutnya
            return None

    @property
    def fast_active(self) -> bool:
        return self._fast is not None

    # ---------- dasar ----------
    def _base(self) -> list[str]:
        return [self.adb_path, "-s", self.serial] if self.serial else [self.adb_path]

    def _cmd(self, *args: str, timeout: float = 30) -> bytes:
        try:
            code, out, err = self._run([*self._base(), *args], timeout)
        except FileNotFoundError as e:
            raise AdbNotFound("adb tidak ditemukan. Pasang Android platform-tools lalu coba lagi.") from e
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb tidak merespons dalam {timeout:.0f} detik: {' '.join(args)}") from e
        if code != 0:
            message = (err or out).decode("utf-8", "replace").strip() or f"adb keluar dengan kode {code}"
            raise AdbError(message)
        return out

    def shell(self, command: str, timeout: float = 30) -> str:
        return self._cmd("shell", command, timeout=timeout).decode("utf-8", "replace")

    def _shell_args(self, *args: str, timeout: float = 30) -> str:
        return self._cmd("shell", *args, timeout=timeout).decode("utf-8", "replace")

    def exec_out(self, command: str, timeout: float = 30) -> bytes:
        return self._cmd("exec-out", command, timeout=timeout)

    # ---------- perangkat ----------
    def connect(self, address: str) -> str:
        """`adb connect host:port` (Wireless debugging / server). adb keluar 0 walau gagal, jadi cek teksnya."""
        out = self._cmd("connect", address, timeout=20).decode("utf-8", "replace").strip()
        if not out.lower().startswith(("connected", "already connected")):
            raise AdbError(out or f"Tidak bisa tersambung ke {address}")
        return out

    def pair(self, address: str, code: str) -> str:
        """`adb pair host:port kode` (Android 11+, kode dari menu Wireless debugging)."""
        out = self._cmd("pair", address, code, timeout=30).decode("utf-8", "replace").strip()
        if "success" not in out.lower():
            raise AdbError(out or f"Gagal memasangkan {address}")
        return out

    def devices(self) -> list[DeviceInfo]:
        out = self._cmd("devices", "-l", timeout=15).decode("utf-8", "replace")
        devices: list[DeviceInfo] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            devices.append(DeviceInfo(serial=parts[0], state=parts[1],
                                      model=info.get("model", "").replace("_", " "),
                                      product=info.get("product", "")))
        return devices

    def android_version(self) -> str:
        return self.shell("getprop ro.build.version.release").strip()

    def packages(self, third_party: bool = True) -> list[str]:
        out = self.shell("pm list packages -3" if third_party else "pm list packages")
        return sorted(line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:"))

    def package_versions(self) -> dict[str, str | None]:
        """Paket pihak ketiga beserta versionName, dalam satu perintah shell."""
        script = ("for p in $(pm list packages -3 | cut -d: -f2); do "
                  "echo \"$p $(dumpsys package $p | grep -m1 versionName)\"; done")
        out = self.shell(script, timeout=60)
        versions: dict[str, str | None] = {}
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            match = re.search(r"versionName=(\S+)", parts[1]) if len(parts) > 1 else None
            versions[parts[0]] = match.group(1) if match else None
        return dict(sorted(versions.items()))

    def install(self, apk_path: str, grant: bool = True) -> None:
        """Pasang (atau timpa) APK. `grant` = beri semua izin runtime otomatis."""
        flags = ["-r", "-g"] if grant else ["-r"]
        out = self._cmd("install", *flags, str(apk_path), timeout=300).decode("utf-8", "replace")
        if "Success" not in out:
            failure = re.search(r"Failure \[([^\]]+)\]", out)
            raise AdbError(f"Gagal memasang APK: {failure.group(1) if failure else out.strip()[:300]}")

    def uninstall(self, package: str) -> None:
        out = self._cmd("uninstall", package, timeout=120).decode("utf-8", "replace")
        if "Success" not in out:
            raise AdbError(f"Gagal menghapus aplikasi {package}: {out.strip()[:200]}")

    def launch(self, package: str) -> None:
        out = self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
        if "No activities found" in out or "monkey aborted" in out:
            raise AdbError(f"Aplikasi {package} tidak punya layar pembuka (launcher) atau tidak terpasang")

    def force_stop(self, package: str) -> None:
        self.shell(f"am force-stop {package}")

    def screen_size(self) -> tuple[int, int]:
        out = self.shell("wm size")
        sizes = dict(re.findall(r"(Physical|Override) size: (\d+x\d+)", out))
        value = sizes.get("Override") or sizes.get("Physical")
        if not value:
            raise AdbError(f"Ukuran layar tidak terbaca: {out.strip()[:120]}")
        w, h = value.split("x")
        return int(w), int(h)

    def current_activity(self) -> tuple[str, str]:
        out = self.shell("dumpsys window")
        match = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([^/\s}]+)/([^\s}]+)\}", out)
        if not match:
            return "", ""
        package, activity = match.group(1), match.group(2)
        if activity.startswith("."):
            activity = package + activity
        return package, activity

    def focus_and_pid(self, package: str) -> tuple[str, str, str | None]:
        """Activity yang tampil + PID aplikasi dalam satu perintah adb (hemat ~0,3 detik per langkah)."""
        out = self.shell(f"dumpsys window | grep mCurrentFocus; echo @@QA@@; pidof {package}; true")
        focus, _, pid = out.partition("@@QA@@")
        match = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([^/\s}]+)/([^\s}]+)\}", focus)
        pkg, activity = (match.group(1), match.group(2)) if match else ("", "")
        if activity.startswith("."):
            activity = pkg + activity
        return pkg, activity, pid.strip() or None

    def pidof(self, package: str) -> str | None:
        try:
            out = self.shell(f"pidof {package}").strip()
        except AdbError:
            return None
        return out or None

    def crash_log(self, package: str) -> str:
        try:
            out = self.shell("logcat -b crash -d -t 200")
        except AdbError:
            return ""
        lines = [ln for ln in out.splitlines() if not ln.startswith("---------")]
        if package not in out:
            return ""
        keep = [re.sub(r"^.*?AndroidRuntime:\s*", "", ln).strip() for ln in lines]
        return "\n".join(ln for ln in keep if ln)[-1500:]

    def clear_crash_log(self) -> None:
        try:
            self.shell("logcat -b crash -c")
        except AdbError:
            pass

    # ---------- layar ----------
    def screencap(self) -> bytes:
        fast = self._fast_call("screenshot_png")
        if fast:
            return fast
        data = self.exec_out("screencap -p")
        if not data.startswith(PNG_MAGIC):
            # Beberapa perangkat lama mengubah \n menjadi \r\n
            fixed = data.replace(b"\r\n", b"\n")
            if not fixed.startswith(PNG_MAGIC):
                raise AdbError("Screenshot HP tidak valid (layar terkunci atau aplikasi melarang screenshot)")
            data = fixed
        return data

    def dump_ui(self) -> str:
        fast = self._fast_call("dump")
        if fast and "<hierarchy" in fast:
            return fast
        out = self.shell(f"uiautomator dump {UI_DUMP_PATH}", timeout=40)
        if "ERROR" in out or "dumped" not in out.lower():
            raise AdbError(f"Gagal membaca elemen layar: {out.strip()[:200]}")
        xml = self.exec_out(f"cat {UI_DUMP_PATH}").decode("utf-8", "replace")
        if "<hierarchy" not in xml:
            raise AdbError("Hasil uiautomator kosong")
        return xml

    # ---------- input ----------
    def tap(self, x: float, y: float) -> None:
        self._shell_args("input", "tap", str(round(x)), str(round(y)))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, ms: int = 300) -> None:
        self._shell_args("input", "swipe", *(str(round(v)) for v in (x1, y1, x2, y2)), str(ms))

    def keyevent(self, code: int) -> None:
        self._shell_args("input", "keyevent", str(code))

    def keyevents(self, *codes: int) -> None:
        """Beberapa tombol dalam satu perintah (lebih cepat daripada satu per satu)."""
        if codes:
            self._shell_args("input", "keyevent", *(str(c) for c in codes))

    def text(self, value: str) -> None:
        if value:
            self._shell_args("input", "text", escape_text(value))
