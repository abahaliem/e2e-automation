from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright
from PIL import Image

from qa_agent import imaging
from qa_agent.drivers.base import DriverCrashed, missing_credential
from qa_agent.drivers.web_dom import ERROR_WATCH_JS, EXTRACT_JS, UI_ERROR_JS, to_element
from qa_agent.evidence import now_iso
from qa_agent.models import Action, ActionResult, Element, Observation, Signal
from qa_agent.orchestrator.fingerprint import fingerprint

TRACKED_RESOURCES = {"document", "xhr", "fetch"}
BENIGN_JS_ERRORS = ("ResizeObserver loop",)
_FATAL_MARKERS = ("has been closed", "Target closed", "Browser closed")
SCREENCAST_FPS = 6
SETTLE_MAX_MS = 3000  # batas menunggu halaman tenang setelah aksi
QUIET_SECONDS = 0.3  # cukup tenang selama ini tanpa request baru
LONG_REQUEST = 1.5  # request yang terbuka lebih lama dari ini dianggap polling/stream, tidak ditunggu
POLL_HITS, POLL_WINDOW = 3, 5.0  # endpoint dipanggil >= 3x dalam 5 detik = polling
SCREENCAST_MAX_WIDTH = 1280
SCREENCAST_QUALITY = 60


def _first_line(e: Exception) -> str:
    lines = str(e).strip().splitlines()
    return (lines[0] if lines else type(e).__name__)[:300]


def _is_fatal(e: Exception) -> bool:
    return any(marker in str(e) for marker in _FATAL_MARKERS)


def is_tracked_url(url: str, domains: list[str]) -> bool:
    """Hanya error dari domain aplikasi yang dihitung (bukan analytics/CDN/Sentry pihak ketiga)."""
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def is_benign_js_error(message: str) -> bool:
    return any(marker in message for marker in BENIGN_JS_ERRORS)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class WebDriver:
    """Driver web berbasis Playwright (sync API)."""

    def __init__(
        self,
        base_url: str,
        *,
        headless: bool = False,
        viewport: tuple[int, int] = (1366, 768),
        request_filter: Callable[[str, str, bool], bool] | None = None,
        tracked_domains: list[str] | None = None,
        max_elements: int = 80,
        action_timeout_ms: int = 15_000,
        navigation_timeout_ms: int = 30_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.viewport = viewport
        self.request_filter = request_filter
        self.tracked_domains = [d.lower() for d in (tracked_domains or [urlsplit(base_url).hostname or ""])]
        self.login_mode = False  # True hanya selama alur login (endpoint login dibuka di production)
        self.max_elements = max_elements
        self.action_timeout_ms = action_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.blocked_requests: list[str] = []
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._frames: list[Any] = []
        self._signals: list[Signal] = []
        # (teks, png, waktu) error yang terlihat di halaman, difoto tepat saat muncul
        self._seen_errors: list[tuple[str, bytes, str]] = []
        self._seen_pending: list[tuple[str, str]] = []  # (teks, waktu) menunggu difoto
        self._seen_since = 0.0
        self._inflight: dict[int, float] = {}  # request yang sedang berjalan → waktu mulai
        self._net_at = 0.0  # waktu aktivitas jaringan terakhir
        self._hits: dict[str, list[float]] = {}  # endpoint → waktu panggilan terakhir (deteksi polling)
        self._credentials: dict[str, str] = {}
        # layar live (CDP screencast)
        self._frame_sink: Callable[[bytes, dict], None] | None = None
        self._streaming = False
        self._cdp: Any = None
        self._last_frame_at = 0.0

    # ---------- siklus hidup ----------
    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)

    def stop(self) -> None:
        self._cdp = None
        for closable in (self._context, self._browser):
            if closable is not None:
                try:
                    closable.close()
                except PlaywrightError:
                    pass
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    def new_session(self, auth_state: Path | None = None) -> None:
        if self._browser is None:
            raise DriverCrashed("Browser belum dijalankan (panggil start())")
        if self._context is not None:
            self._cdp = None
            try:
                self._context.close()
            except PlaywrightError:
                pass
        state = str(auth_state) if auth_state and Path(auth_state).exists() else None
        width, height = self.viewport
        # Request dari Service Worker tidak melewati context.route → blok SW saat filter production aktif
        service_workers = "block" if self.request_filter is not None else "allow"
        self._context = self._browser.new_context(viewport={"width": width, "height": height}, storage_state=state,
                                                  service_workers=service_workers)
        if self.request_filter is not None:
            self._context.route("**/*", self._route)
        try:
            self._context.expose_binding("__qaErrorSeen", self._on_error_seen)
            self._context.add_init_script(ERROR_WATCH_JS)
        except PlaywrightError:
            pass  # pemantau error hanya pelengkap
        page = self._context.new_page()
        page.set_default_timeout(self.action_timeout_ms)
        page.set_default_navigation_timeout(self.navigation_timeout_ms)
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_request_done)
        page.on("requestfailed", self._on_request_done)
        self._inflight = {}
        self._hits = {}
        self._net_at = 0.0
        self._page = page
        self._signals = []
        self._seen_errors = []
        self._seen_pending = []
        self._frames = []
        if self._streaming and self._frame_sink is not None:
            self._start_screencast()

    # ---------- layar live ----------
    def set_frame_sink(self, sink: Callable[[bytes, dict], None] | None) -> None:
        self._frame_sink = sink
        if sink is None:
            self._stop_screencast()
        elif self._streaming:
            self._start_screencast()

    def set_streaming(self, enabled: bool) -> None:
        self._streaming = enabled
        if enabled and self._frame_sink is not None:
            self._start_screencast()
        else:
            self._stop_screencast()

    def pump(self, ms: int = 50) -> None:
        """Beri kesempatan Playwright memproses event (frame live) saat worker sedang menunggu."""
        if self._page is None:
            return
        try:
            self._page.wait_for_timeout(ms)
        except PlaywrightError:
            pass
        self._flush_seen()

    def _start_screencast(self) -> None:
        if self._page is None or self._cdp is not None:
            return
        try:
            cdp = self._context.new_cdp_session(self._page)
            cdp.on("Page.screencastFrame", lambda params: self._on_frame(cdp, params))
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": SCREENCAST_QUALITY,
                                              "maxWidth": SCREENCAST_MAX_WIDTH, "maxHeight": SCREENCAST_MAX_WIDTH,
                                              "everyNthFrame": 1})
            self._cdp = cdp
        except PlaywrightError:
            self._cdp = None

    def _stop_screencast(self) -> None:
        cdp, self._cdp = self._cdp, None
        if cdp is None:
            return
        try:
            cdp.send("Page.stopScreencast")
            cdp.detach()
        except PlaywrightError:
            pass

    def _on_frame(self, cdp: Any, params: dict) -> None:
        try:
            cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except PlaywrightError:
            return
        if cdp is not self._cdp or self._frame_sink is None:
            return
        now = time.monotonic()
        if self._seen_pending and now - self._seen_since >= 0.1:
            # frame live pertama setelah error terlihat = foto bukti (tanpa memanggil API Playwright di callback)
            try:
                img = Image.open(BytesIO(base64.b64decode(params["data"])))
                buf = BytesIO()
                img.save(buf, "PNG")
                pending, self._seen_pending = self._seen_pending, []
                self._seen_errors.extend((text, buf.getvalue(), at) for text, at in pending)
            except Exception:  # noqa: BLE001
                pass
        if now - self._last_frame_at < 1.0 / SCREENCAST_FPS:
            return  # batasi ~6 fps
        self._last_frame_at = now
        meta = params.get("metadata") or {}
        width, height = self.viewport
        info = {"width": int(meta.get("deviceWidth") or width), "height": int(meta.get("deviceHeight") or height)}
        try:
            self._frame_sink(base64.b64decode(params["data"]), info)
        except Exception:
            pass  # penonton bermasalah tidak boleh menghentikan run

    def save_auth_state(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(path))

    @property
    def page(self) -> Any:
        if self._page is None:
            raise DriverCrashed("Sesi browser belum dibuat atau sudah ditutup")
        return self._page

    @property
    def current_url(self) -> str:
        return self.page.url

    # ---------- event ----------
    def _route(self, route: Any) -> None:
        request = route.request
        if self.request_filter is not None and self.request_filter(request.method, request.url, self.login_mode):
            self.blocked_requests.append(f"{request.method} {request.url}")
            self._signals.append(Signal(kind="blocked_request", message="Request diblok mode production",
                                        method=request.method, url=request.url))
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            self._signals.append(Signal(kind="console_error", message=msg.text[:300]))

    def _on_page_error(self, error: Any) -> None:
        message = str(error)
        if not is_benign_js_error(message):
            self._signals.append(Signal(kind="page_error", message=message[:300]))

    def _on_response(self, response: Any) -> None:
        if (response.status >= 400 and response.request.resource_type in TRACKED_RESOURCES
                and is_tracked_url(response.url, self.tracked_domains)):
            self._signals.append(Signal(kind="http_error", message=f"HTTP {response.status}", status=response.status,
                                        url=response.url, method=response.request.method))

    def _on_error_seen(self, source: Any, text: str) -> None:
        """Dipanggil dari halaman saat toast/alert error muncul. Hanya mencatat: memanggil API Playwright dari
        callback binding membuat macet. Fotonya diambil dari frame layar live berikutnya atau di _flush_seen()."""
        text = str(text or "")[:300]
        known = [t for t, _, _ in self._seen_errors] + [t for t, _ in self._seen_pending]
        if not text or text in known or len(known) >= 10:
            return
        self._seen_pending.append((text, now_iso()))
        self._seen_since = time.monotonic()

    def _flush_seen(self) -> None:
        """Foto layar untuk error yang baru terlihat (dipanggil saat kendali kembali ke Python)."""
        if not self._seen_pending or self._page is None:
            return
        pending, self._seen_pending = self._seen_pending, []
        try:
            png = self._page.screenshot()
        except Exception:  # noqa: BLE001
            png = b""
        self._seen_errors.extend((text, png, at) for text, at in pending)

    def _drain_signals(self) -> list[Signal]:
        signals, self._signals = self._signals, []
        return signals

    # ---------- navigasi & observasi ----------
    def goto(self, location: str) -> None:
        url = urljoin(self.base_url + "/", location)
        for attempt in range(2):  # timeout navigasi: coba 1× lagi (spec §9)
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                break
            except PlaywrightTimeout:
                if attempt == 1:
                    raise
            except PlaywrightError as e:
                if _is_fatal(e):
                    raise DriverCrashed(_first_line(e)) from e
                raise
        self._settle()

    def _settle(self) -> None:
        """Tunggu halaman tenang setelah aksi, tanpa terjebak polling.

        `networkidle` bawaan Playwright butuh 0,5 detik tanpa request sama sekali; dashboard yang terus polling
        (statistik live, debugbar, websocket fallback) tidak pernah idle sehingga setiap langkah selalu menunggu
        penuh 3 detik, dua kali per langkah. Di sini yang ditunggu hanya request yang baru dimulai (< LONG_REQUEST
        detik); request yang terbuka lama (long-polling, stream) diabaikan, dan cukup tenang QUIET_SECONDS."""
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=SETTLE_MAX_MS)
            begin = time.monotonic()
            deadline = begin + SETTLE_MAX_MS / 1000
            while True:
                now = time.monotonic()
                busy = any(now - started < LONG_REQUEST for started in self._inflight.values())
                # "tenang" dihitung sejak mulai menunggu: request yang dipicu aksi sesaat kemudian tetap ditunggu
                if (not busy and now - max(self._net_at, begin) >= QUIET_SECONDS) or now >= deadline:
                    break
                self.page.wait_for_timeout(50)
        except PlaywrightTimeout:
            pass
        except PlaywrightError as e:
            if _is_fatal(e):
                raise DriverCrashed(_first_line(e)) from e

    def _on_request(self, request: Any) -> None:
        if request.resource_type in ("websocket", "eventsource", "media"):
            return
        now = time.monotonic()
        # Endpoint yang dipanggil berulang-ulang = polling (statistik live, notifikasi): tidak ditunggu
        key = f"{request.method} {urlsplit(request.url).path}"
        hits = [t for t in self._hits.get(key, []) if now - t < POLL_WINDOW] + [now]
        self._hits[key] = hits[-5:]
        if len(hits) >= POLL_HITS:
            return
        self._inflight[id(request)] = now
        self._net_at = now

    def _on_request_done(self, request: Any) -> None:
        if self._inflight.pop(id(request), None) is not None:
            self._net_at = time.monotonic()

    def _scan_frames(self) -> list[tuple[Any, tuple[float, float]]]:
        main = self.page.main_frame
        frames: list[tuple[Any, tuple[float, float]]] = [(main, (0.0, 0.0))]
        origin = _origin(main.url)
        for child in main.child_frames:
            if _origin(child.url) != origin:
                continue  # iframe lintas domain tidak didukung
            try:
                box = child.frame_element().bounding_box()
            except PlaywrightError:
                continue
            if box:
                frames.append((child, (box["x"], box["y"])))
        return frames

    def _observe_once(self) -> Observation:
        self._flush_seen()
        self._settle()
        self._flush_seen()
        elements: list[Element] = []
        frames: list[Any] = []
        for frame, offset in self._scan_frames():
            remaining = self.max_elements - len(elements)
            if remaining <= 0:
                break
            raws = frame.evaluate(EXTRACT_JS, [remaining, len(elements) + 1])
            frame_index = len(frames)
            frames.append(frame)
            elements.extend(to_element(raw, frame_index, offset) for raw in raws)
        self._frames = frames
        ui_errors = self.page.evaluate(UI_ERROR_JS)
        png = self.page.screenshot()
        url = self.page.url
        at = now_iso()
        evidence: dict[str, bytes] = {}
        signals = self._drain_signals()
        for text in ui_errors:
            signals.append(Signal(kind="ui_error", message=text, at=at))
            evidence[text] = png
        # error yang sempat muncul lalu hilang sebelum agent melihat layar (toast, popup singkat)
        seen, self._seen_errors = self._seen_errors, []
        for text, shot, when in seen:
            if any(text in u or u in text for u in ui_errors):
                if shot:
                    evidence[next(u for u in ui_errors if text in u or u in text)] = shot
                continue
            message = f"Pesan muncul sesaat lalu hilang: {text}"[:300]
            signals.append(Signal(kind="ui_error", message=message, at=when))
            if shot:
                evidence[message] = shot
        for s in signals:  # error JavaScript / server: bukti = layar saat ini
            if s.kind in ("page_error", "http_error") and s.message not in evidence and (s.status or 500) >= 500:
                evidence[s.message] = png
        return Observation(
            location=url,
            title=self.page.title(),
            elements=elements,
            signals=signals,
            evidence=evidence,
            screenshot_annotated=imaging.annotate(png, elements),
            fingerprint=fingerprint(url, elements),
        )

    def observe(self) -> Observation:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                return self._observe_once()
            except PlaywrightError as e:  # mis. "Execution context was destroyed" saat navigasi
                if _is_fatal(e):
                    raise DriverCrashed(_first_line(e)) from e
                last_error = e
                self._settle()
        assert last_error is not None
        raise last_error

    def screenshot(self, highlight: Element | None = None) -> bytes:
        try:
            png = self.page.screenshot()
        except PlaywrightError as e:
            if _is_fatal(e):
                raise DriverCrashed(_first_line(e)) from e
            raise
        return imaging.highlight(png, highlight.bbox) if highlight is not None else png

    # ---------- aksi ----------
    def set_credentials(self, username: str, password: str) -> None:
        self._credentials = {"{{username}}": username, "{{password}}": password}

    def _resolve(self, text: str | None, *, allow_password: bool) -> str:
        """Ganti placeholder kredensial. {{password}} hanya diisi ke field bertipe password."""
        text = text or ""
        for placeholder, real in self._credentials.items():
            if placeholder == "{{password}}" and not allow_password:
                continue
            text = text.replace(placeholder, real)
        return text

    def _locator(self, element: Element) -> Any:
        return self._frames[element.frame].locator(f'[data-qa-idx="{element.index}"]').first

    def _select(self, locator: Any, value: str) -> None:
        try:
            locator.select_option(label=value, timeout=3000)
        except PlaywrightError:
            locator.select_option(value=value)

    def viewport_size(self) -> dict:
        width, height = self.viewport
        return {"width": width, "height": height}

    def manual_input(self, event: dict) -> ActionResult:
        """Input manual QA dari layar live. Koordinat ternormalisasi 0..1 dikali ukuran viewport.

        Tidak lewat Guard kata kunci; filter jaringan production (context.route) tetap aktif.
        """
        kind = event.get("kind")
        try:
            if kind == "click":
                width, height = self.viewport
                x = min(max(float(event["x"]), 0.0), 1.0) * width
                y = min(max(float(event["y"]), 0.0), 1.0) * height
                self.page.mouse.click(x, y)
            elif kind == "type":
                self.page.keyboard.type(str(event.get("text", "")))
            elif kind == "key":
                self.page.keyboard.press(str(event["key"]))
            elif kind == "scroll":
                self.page.mouse.wheel(0, int(event.get("dy", 0)))
            else:
                return ActionResult(ok=False, error=f"Jenis input manual tidak dikenal: {kind}")
            if kind in ("click", "key"):
                # Klik mouse mentah kembali sebelum navigasi/submit dimulai; beri waktu request berangkat.
                self.page.wait_for_timeout(300)
            self._settle()
            return ActionResult(ok=True)
        except (KeyError, TypeError, ValueError) as e:
            return ActionResult(ok=False, error=f"Input manual tidak valid: {e}")
        except PlaywrightTimeout as e:
            return ActionResult(ok=False, error=f"Timeout: {_first_line(e)}")
        except PlaywrightError as e:
            return ActionResult(ok=False, error=_first_line(e), fatal=_is_fatal(e))
        except DriverCrashed as e:
            return ActionResult(ok=False, error=str(e), fatal=True)

    def execute(self, action: Action, element: Element | None) -> ActionResult:
        kind = action.action
        if kind in ("click", "type", "select"):
            if element is None:
                return ActionResult(ok=False, error=f"Aksi {kind} butuh elemen")
            if element.frame >= len(self._frames):
                return ActionResult(ok=False, error="Elemen berasal dari observasi lama; observasi ulang")
        try:
            if kind == "click":
                self._locator(element).click()
            elif kind == "type":
                missing = missing_credential(action.value, self._credentials)
                if missing:
                    return ActionResult(ok=False, error=missing)
                self._locator(element).fill(self._resolve(action.value, allow_password=element.input_type == "password"))
            elif kind == "select":
                self._select(self._locator(element), action.value or "")
            elif kind == "scroll":
                self.page.mouse.wheel(0, -600 if action.value == "up" else 600)
            elif kind == "back":
                self.page.go_back(wait_until="domcontentloaded")
            elif kind == "navigate":
                self.goto(action.value or "/")
            elif kind == "wait":
                self.page.wait_for_timeout(min(float(action.value or 2), 10.0) * 1000)
            self._settle()
            return ActionResult(ok=True)
        except PlaywrightTimeout as e:
            return ActionResult(ok=False, error=f"Timeout: {_first_line(e)}")
        except PlaywrightError as e:
            return ActionResult(ok=False, error=_first_line(e), fatal=_is_fatal(e))
        except DriverCrashed as e:
            return ActionResult(ok=False, error=str(e), fatal=True)
        except ValueError as e:
            return ActionResult(ok=False, error=f"Nilai tidak valid: {e}")
