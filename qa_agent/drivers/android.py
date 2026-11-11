"""Driver Android lewat adb: antarmuka sama dengan WebDriver sehingga AgentLoop/Explorer/DeepRunner dipakai ulang.

Lokasi layar: `android://<paket>/<Activity>#<kunci-layar>`. Driver mencatat jalur tap dari awal aplikasi ke setiap
layar supaya `goto` bisa kembali ke layar mana pun (aplikasi Android umumnya tidak bisa dibuka langsung per layar).
"""
from __future__ import annotations

import json
import re
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from PIL import Image

from qa_agent import imaging
from qa_agent.drivers.adb import AdbError
from qa_agent.drivers.android_dom import parse_ui, screen_key
from qa_agent.drivers.base import DriverCrashed, missing_credential
from qa_agent.evidence import now_iso
from qa_agent.models import Action, ActionResult, Element, Observation, Signal
from qa_agent.orchestrator.fingerprint import fingerprint

KEYCODES = {"Enter": 66, "Tab": 61, "Escape": 4, "Back": 4, "Backspace": 67, "Delete": 112, "Home": 3,
            "ArrowUp": 19, "ArrowDown": 20, "ArrowLeft": 21, "ArrowRight": 22, "Space": 62}
KEY_BACK, KEY_DEL, KEY_MOVE_END = 4, 67, 123
_FATAL = re.compile(r"device .*not found|no devices|device offline|device unauthorized|closed", re.IGNORECASE)
_SYSTEM_DIALOG = re.compile(r"isn.t responding|tidak merespons|has stopped|telah berhenti|keeps stopping|terus berhenti",
                            re.IGNORECASE)
_ERROR_TEXT = re.compile(
    r"error|gagal|failed|failure|exception|kesalahan|tidak dapat|tidak bisa|timeout|time out|invalid|unauthori[sz]ed"
    r"|forbidden|not found|something went wrong|oops|server error|koneksi (terputus|gagal)|no connection|denied"
    r"|ditolak|tidak valid|salah",
    re.IGNORECASE)
AI_IMAGE_WIDTH = 720
FRAME_WIDTH = 720


def _shrink_png(png: bytes, max_width: int) -> bytes:
    img = Image.open(BytesIO(png))
    if img.width <= max_width:
        return png
    img = img.convert("RGB").resize((max_width, round(img.height * max_width / img.width)))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _center(el: Element) -> tuple[float, float]:
    x, y, w, h = el.bbox
    return x + w / 2, y + h / 2


class AndroidDriver:
    def __init__(self, adb: Any, package: str, *, max_elements: int = 80, settle_seconds: float = 0.8,
                 sleep: Callable[[float], None] = time.sleep, frame_interval: float = 0.15) -> None:
        self.adb = adb
        self.package = package
        self.max_elements = max_elements
        self.settle_seconds = settle_seconds
        self._sleep = sleep
        self.frame_interval = frame_interval
        self.login_mode = False  # kompatibel dengan WebDriver (tidak ada filter jaringan di Android)
        self.keeps_login = True  # membuka ulang aplikasi tidak menghapus sesi login (beda dengan konteks browser baru)
        self.back_probe = True  # explorer boleh menekan Kembali untuk menutup popup/form yang menutupi layar lain
        self._recording: list[dict] | None = None
        self._transient: list[str] = []  # teks error dari popup/snackbar yang tampil sesaat setelah tap
        self._transient_shots: dict[str, bytes] = {}  # screenshot tepat saat popup error itu terbaca
        self.frame_workers = 2  # screencap HP lambat (~0,3-0,8 dtk): dua pengambil bergantian supaya live lebih mulus
        self.blocked_requests: list[str] = []
        self._size = (1080, 1920)
        self._credentials: dict[str, str] = {}
        self._paths: dict[str, list[dict]] = {}
        self._location = ""
        self._path_here: list[dict] = []
        self._pending: tuple[str, dict] | None = None
        self._alive = False
        self._crash_reported = False
        # layar live
        self._frame_sink: Callable[[bytes, dict], None] | None = None
        self._streaming = False
        self._frame_threads: list[threading.Thread] = []
        self._frame_stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._last_frame_at = 0.0

    # ---------- siklus hidup ----------
    def start(self) -> None:
        try:
            self._size = tuple(self.adb.screen_size())  # type: ignore[assignment]
        except AdbError as e:
            raise DriverCrashed(f"HP tidak bisa diakses: {e}") from e
        clear = getattr(self.adb, "clear_crash_log", None)
        if clear:
            clear()

    def stop(self) -> None:
        self._stop_frames()

    def new_session(self, auth_state: Path | None = None) -> None:
        """Buka ulang aplikasi dari awal. Data aplikasi (termasuk sesi login) tidak dihapus."""
        try:
            self.adb.force_stop(self.package)
            self.adb.launch(self.package)
        except AdbError as e:
            if _FATAL.search(str(e)):
                raise DriverCrashed(str(e)) from e
            raise
        self._alive = True
        self._crash_reported = False
        self._path_here = []
        self._pending = None
        self._location = ""
        self._sleep(max(self.settle_seconds, 1.5))
        self._wait_ready()

    def _wait_ready(self, polls: int = 24, interval: float = 0.5) -> None:
        """Tunggu splash/loading selesai: layar punya elemen dan sama pada dua pembacaan berturut-turut (maks ~12 detik)."""
        previous = None
        for _ in range(polls):
            elements = self._dump()
            key = screen_key(elements) if elements else None
            if key is not None and key == previous:
                return
            previous = key
            self._sleep(interval)

    # ---------- rekam & putar ulang langkah (mis. jalur logout) ----------
    def start_recording(self) -> None:
        self._recording = []

    def stop_recording(self) -> list[dict]:
        steps, self._recording = (self._recording or []), None
        return steps

    def replay_steps(self, steps: list[dict]) -> bool:
        """Putar ulang tap yang direkam. False bila ada langkah yang tidak ditemukan di layar."""
        for step in steps:
            if step.get("key") == "back":
                self.adb.keyevent(KEY_BACK)
                self._sleep(self.settle_seconds)
                continue
            el = None
            for _ in range(3):  # beri waktu menu/dialog muncul
                el = self._find_step(step, self._dump())
                if el is not None:
                    break
                self._sleep(self.settle_seconds)
            if el is None:
                return False
            self.adb.tap(*_center(el))
            self._sleep(self.settle_seconds)
        self._wait_ready(polls=8)
        return True

    def save_auth_state(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"platform": "android", "package": self.package}), encoding="utf-8")

    # ---------- jalur navigasi ----------
    def path_to(self, location: str) -> list[dict]:
        return list(self._paths.get(location, []))

    def register_paths(self, paths: dict[str, list[dict]]) -> None:
        for loc, steps in paths.items():
            if steps is not None:
                self._paths.setdefault(loc, list(steps))

    def _start_location(self, location: str) -> bool:
        parts = urlsplit(location)
        return location in ("", "/") or (parts.scheme == "android" and parts.path in ("", "/") and not parts.fragment)

    # ---------- observasi ----------
    def _dump(self) -> list[Element]:
        last: Exception | None = None
        for attempt in range(3):
            try:
                return parse_ui(self.adb.dump_ui(), self.max_elements, self._size)
            except AdbError as e:
                if _FATAL.search(str(e)):
                    raise DriverCrashed(str(e)) from e
                last = e
                self._sleep(0.6 * (attempt + 1))
            except Exception as e:  # XML rusak
                last = e
                self._sleep(0.4)
        self._dump_error = str(last)
        return []

    def _locate(self, elements: list[Element]) -> str:
        package, activity = self.adb.current_activity()
        package = package or self.package
        short = activity.rsplit(".", 1)[-1] if activity else "Layar"
        location = f"android://{package}/{short}#{screen_key(elements)}"
        self._record(location)
        return location

    def _record(self, location: str) -> None:
        """Catat jalur ke layar baru berdasarkan tap terakhir yang membuatnya berpindah."""
        if self._pending is not None:
            origin, step = self._pending
            self._pending = None
            if location != origin:
                base = self._paths.get(origin, self._path_here if origin == self._location else [])
                path = list(base) + [step]
                self._paths.setdefault(location, path)
                self._path_here = self._paths[location]
        elif location in self._paths:
            self._path_here = self._paths[location]
        if not self._location and not self._path_here:
            self._paths.setdefault(location, [])
        self._location = location

    @property
    def current_url(self) -> str:
        return self._locate(self._dump())

    def observe(self) -> Observation:
        self._dump_error = ""
        elements = self._dump()
        location = self._locate(elements)
        png = self.screenshot()
        evidence: dict[str, bytes] = {}
        signals = self._signals(elements, evidence)
        if not elements and self._dump_error:
            signals.append(Signal(kind="ui_error", message=f"Elemen layar tidak terbaca: {self._dump_error[:200]}"))
        for s in signals:  # error yang masih tampil (crash dialog dll.): bukti = layar saat ini
            if (s.kind in ("ui_error", "page_error") and s.message not in evidence and png
                    and not s.message.startswith("Pesan muncul sesaat")):
                evidence[s.message] = png
        title = next((e.name for e in elements if e.role == "text"), location.rsplit("/", 1)[-1].split("#")[0])
        return Observation(
            location=location, title=title, elements=elements, signals=signals, evidence=evidence,
            screenshot_annotated=_shrink_png(imaging.annotate(png, elements), AI_IMAGE_WIDTH),
            fingerprint=fingerprint(location, elements),
        )

    def _watch_transient(self) -> None:
        """Baca layar sekali tepat setelah tap: popup/snackbar error yang hilang sendiri tetap tertangkap."""
        self._sleep(0.3)
        try:
            elements = parse_ui(self.adb.dump_ui(), self.max_elements, self._size)
        except Exception:
            return
        shot: bytes | None = None
        for el in elements:
            text = (el.name or "").strip()
            if text and _ERROR_TEXT.search(text) and text not in self._transient:
                self._transient.append(text)
                if shot is None:  # foto sekali, selagi popup masih tampil
                    try:
                        shot = self.adb.screencap()
                    except Exception:
                        shot = b""
                if shot:
                    self._transient_shots[text] = shot

    def _signals(self, elements: list[Element], evidence: dict[str, bytes] | None = None) -> list[Signal]:
        signals: list[Signal] = []
        if self._transient:
            visible = {(e.name or "").strip() for e in elements}
            for text in self._transient:
                if text not in visible:  # yang masih tampil sudah terlihat agent di daftar elemen
                    message = f"Pesan muncul sesaat lalu hilang: {text}"[:300]
                    signals.append(Signal(kind="ui_error", message=message, at=now_iso()))
                    if evidence is not None and text in self._transient_shots:
                        evidence[message] = self._transient_shots[text]
            self._transient = []
            self._transient_shots = {}
        if self._alive and not self._crash_reported and not self.adb.pidof(self.package):
            self._crash_reported = True
            log = self.adb.crash_log(self.package)
            detail = " | ".join(ln.strip() for ln in log.splitlines()[:4] if ln.strip())
            signals.append(Signal(kind="page_error",
                                  message=("Aplikasi tertutup sendiri (crash)" + (f": {detail}" if detail else ""))[:300]))
        for el in elements:
            if _SYSTEM_DIALOG.search(el.name):
                signals.append(Signal(kind="page_error", message=f"Dialog sistem Android: {el.name}"[:300]))
                break
        return signals

    def screenshot(self, highlight: Element | None = None) -> bytes:
        try:
            png = self.adb.screencap()
        except AdbError as e:
            if _FATAL.search(str(e)):
                raise DriverCrashed(str(e)) from e
            raise
        return imaging.highlight(png, highlight.bbox) if highlight is not None else png

    # ---------- navigasi ----------
    def goto(self, location: str) -> None:
        if location.startswith(("http://", "https://")):
            raise RuntimeError(f"Lokasi web tidak berlaku untuk aplikasi Android: {location}")
        if self._start_location(location):
            self.new_session(None)
            return
        current = self.current_url
        if current == location:
            return
        target = self._paths.get(location)
        if target is None:
            raise RuntimeError(f"Layar {location} tidak bisa dicapai (jalur belum tercatat)")
        here = self._paths.get(current)
        if here is not None and len(here) > len(target) and here[: len(target)] == target and len(here) - len(target) <= 2:
            for _ in range(len(here) - len(target)):
                self.adb.keyevent(KEY_BACK)
                self._sleep(self.settle_seconds)
            if self.current_url == location:
                return
        self.new_session(None)
        i = 0
        while i < len(target):
            if target[i].get("key") == "back":
                self.adb.keyevent(KEY_BACK)
                self._sleep(self.settle_seconds)
                i += 1
                continue
            elements = self._dump()
            if self._is_login(elements):
                return  # sesi login habis: biarkan AuthManager login dulu, lalu goto dipanggil lagi
            el = self._find_step(target[i], elements)
            if el is None:
                # Langkah yang tidak ada di layar dilewati (mis. tombol login saat aplikasi sudah login).
                j = next((k for k in range(i + 1, len(target)) if self._find_step(target[k], elements)), None)
                if j is None:
                    if self._locate(elements) == location:
                        return  # sudah tiba (langkah sisa tidak diperlukan, mis. tombol login)
                    raise RuntimeError(f"Layar {location} tidak bisa dicapai: '{target[i].get('name')}' tidak ditemukan")
                i, el = j, self._find_step(target[j], elements)
            self.adb.tap(*_center(el))  # type: ignore[arg-type]
            self._sleep(self.settle_seconds)
            i += 1
        self._path_here = list(target)
        elements = self._dump()
        reached = self._locate(elements)
        if reached != location and not self._is_login(elements):
            if not target:
                raise RuntimeError(
                    "Layar awal test case ini tidak tampil saat aplikasi dibuka. Layar tersebut kemungkinan hanya muncul "
                    "pada kondisi tertentu (mis. popup/form yang muncul otomatis), jadi test case tidak bisa dijalankan sekarang"
                    f" ({location}, yang tampil {reached})")
            raise RuntimeError(f"Layar {location} tidak bisa dicapai (tiba di {reached})")

    @staticmethod
    def _find_step(step: dict, elements: list[Element]) -> Element | None:
        return next((e for e in elements if step.get("selector") and e.selector == step["selector"]
                     and e.name == step.get("name")), None) or \
            next((e for e in elements if e.role == step.get("role") and e.name == step.get("name")), None)

    def _is_login(self, elements: list[Element]) -> bool:
        return Observation(location=self._location or f"android://{self.package}/", elements=elements).is_login_screen

    # ---------- aksi ----------
    def set_credentials(self, username: str, password: str) -> None:
        self._credentials = {"{{username}}": username, "{{password}}": password}

    def _resolve(self, text: str | None, *, allow_password: bool) -> str:
        text = text or ""
        for placeholder, real in self._credentials.items():
            if placeholder == "{{password}}" and not allow_password:
                continue
            text = text.replace(placeholder, real)
        return text

    def _keys(self, *codes: int) -> None:
        many = getattr(self.adb, "keyevents", None)
        if many:
            many(*codes)
        else:
            for c in codes:
                self.adb.keyevent(c)

    def _scroll(self, down: bool) -> None:
        w, h = self._size
        y1, y2 = (h * 0.7, h * 0.3) if down else (h * 0.3, h * 0.7)
        self.adb.swipe(w / 2, y1, w / 2, y2, 300)

    def _error(self, e: Exception) -> ActionResult:
        text = str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__
        return ActionResult(ok=False, error=text, fatal=isinstance(e, DriverCrashed) or bool(_FATAL.search(text)))

    def execute(self, action: Action, element: Element | None) -> ActionResult:
        kind = action.action
        if kind in ("click", "type", "select") and element is None:
            return ActionResult(ok=False, error=f"Aksi {kind} butuh elemen")
        origin = self._location
        try:
            if kind in ("click", "select"):
                self.adb.tap(*_center(element))  # type: ignore[arg-type]
                step = {"role": element.role, "name": element.name, "selector": element.selector}  # type: ignore[union-attr]
                self._pending = (origin, step)
                if self._recording is not None:
                    self._recording.append(dict(step))
                self._watch_transient()
                if kind == "select" and action.value:
                    self._sleep(self.settle_seconds)
                    target = next((e for e in self._dump() if e.name.lower() == action.value.lower()), None)
                    if target is None:
                        return ActionResult(ok=False, error=f"Opsi '{action.value}' tidak ditemukan")
                    self.adb.tap(*_center(target))
            elif kind == "type":
                missing = missing_credential(action.value, self._credentials)
                if missing:
                    return ActionResult(ok=False, error=missing)
                value = self._resolve(action.value, allow_password=element.input_type == "password")  # type: ignore[union-attr]
                self.adb.tap(*_center(element))  # type: ignore[arg-type]
                self._sleep(0.4)  # beri waktu keyboard HP terhubung ke field (penting untuk Flutter/Compose)
                existing = 32 if element.input_type == "password" else len(element.value or "") + 4  # type: ignore[union-attr]
                self._keys(KEY_MOVE_END, *([KEY_DEL] * existing))
                self.adb.text(value)
            elif kind == "scroll":
                self._scroll(action.value != "up")
            elif kind == "back":
                self.adb.keyevent(KEY_BACK)
                # Kembali juga bagian jalur (mis. menutup popup yang menutupi halaman utama)
                self._pending = (origin, {"key": "back"})
                if self._recording is not None:
                    self._recording.append({"key": "back"})
            elif kind == "navigate":
                self.goto(action.value or "/")
            elif kind == "wait":
                self._sleep(min(float(action.value or 2), 10.0))
                return ActionResult(ok=True)
            self._sleep(self.settle_seconds)
            return ActionResult(ok=True)
        except (AdbError, DriverCrashed, RuntimeError, ValueError) as e:
            return self._error(e)

    def viewport_size(self) -> dict:
        return {"width": self._size[0], "height": self._size[1]}

    def manual_input(self, event: dict) -> ActionResult:
        """Input QA dari layar live. Koordinat ternormalisasi 0..1 dikali ukuran layar HP."""
        kind = event.get("kind")
        try:
            w, h = self._size
            if kind == "click":
                x = min(max(float(event["x"]), 0.0), 1.0) * w
                y = min(max(float(event["y"]), 0.0), 1.0) * h
                self.adb.tap(x, y)
            elif kind == "type":
                self.adb.text(str(event.get("text", "")))
            elif kind == "key":
                code = KEYCODES.get(str(event.get("key")))
                if code is None:
                    return ActionResult(ok=False, error=f"Tombol tidak dikenal: {event.get('key')}")
                self.adb.keyevent(code)
            elif kind == "scroll":
                self._scroll(int(event.get("dy", 0)) >= 0)
            else:
                return ActionResult(ok=False, error=f"Jenis input manual tidak dikenal: {kind}")
            self._sleep(self.settle_seconds)
            return ActionResult(ok=True)
        except (KeyError, TypeError) as e:
            return ActionResult(ok=False, error=f"Input manual tidak valid: {e}")
        except (AdbError, DriverCrashed, ValueError) as e:
            return self._error(e)

    # ---------- layar live ----------
    def set_frame_sink(self, sink: Callable[[bytes, dict], None] | None) -> None:
        self._frame_sink = sink
        if sink is None:
            self._stop_frames()
        elif self._streaming:
            self._start_frames()

    def set_streaming(self, enabled: bool) -> None:
        self._streaming = enabled
        if enabled and self._frame_sink is not None:
            self._start_frames()
        else:
            self._stop_frames()

    def pump(self, ms: int = 50) -> None:
        """Frame dikirim dari thread sendiri; cukup menunggu sebentar."""
        time.sleep(ms / 1000)

    def _start_frames(self) -> None:
        if any(t.is_alive() for t in self._frame_threads):
            return
        self._frame_stop.clear()
        self._frame_threads = []
        for i in range(max(1, self.frame_workers)):
            t = threading.Thread(target=self._frame_loop, args=(i,), name=f"android-frames-{i}", daemon=True)
            self._frame_threads.append(t)
            t.start()

    def _stop_frames(self) -> None:
        self._frame_stop.set()
        threads, self._frame_threads = self._frame_threads, []
        for t in threads:
            if t is not threading.current_thread():
                t.join(2)

    def _frame_loop(self, index: int = 0) -> None:
        # Pengambil kedua mulai setengah interval kemudian, supaya frame datang bergantian, bukan bersamaan.
        if index and self._frame_stop.wait(self.frame_interval / 2 * index):
            return
        while not self._frame_stop.is_set():
            sink = self._frame_sink
            if sink is None:
                break
            started = time.monotonic()
            try:
                jpeg = imaging.to_jpeg(self.adb.screencap(), max_width=FRAME_WIDTH, quality=60)
                with self._frame_lock:
                    if started < self._last_frame_at:
                        continue  # frame yang lebih baru sudah terkirim: jangan mundur
                    self._last_frame_at = started
                sink(jpeg, {"width": self._size[0], "height": self._size[1]})
            except Exception:
                pass  # HP sibuk / dicabut: coba lagi di putaran berikutnya
            self._frame_stop.wait(self.frame_interval)
