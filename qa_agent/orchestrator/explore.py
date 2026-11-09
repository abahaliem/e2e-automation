from __future__ import annotations

import time
from collections import deque
from typing import Callable
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from qa_agent.agent import prompts
from qa_agent.agent.control import RunControl
from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient, LLMError
from qa_agent.models import Action, AppMap, Observation, ScreenInfo, StepRecord
from qa_agent.orchestrator.auth import AuthManager, LoginFailed
from qa_agent.orchestrator.fingerprint import normalize_location

MAX_CLICK_PROBES = 12
NAV_ROLES = ("button", "link", "tab", "menuitem", "listitem", "image")


class ScreenSummary(BaseModel):
    module: str = "Lainnya"
    page_name: str = ""
    purpose: str = ""
    forms: list[dict] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    nav_candidates: list[int] = Field(default_factory=list)


def _clean_href(href: str) -> str:
    """Buang anchor biasa (#bagian), pertahankan hash-route SPA (#/halaman)."""
    fragment = urlsplit(href).fragment
    if fragment and not fragment.startswith("/"):
        return href.split("#", 1)[0]
    return href


class Explorer:
    def __init__(
        self,
        *,
        driver: Driver,
        llm: LLMClient,
        guard: Guard,
        store: RunStore,
        auth: AuthManager | None,
        start_url: str,
        max_screens: int = 60,
        max_depth: int = 5,
        max_minutes: int = 45,
        vision: bool = True,
        clock: Callable[[], float] = time.monotonic,
        should_stop: Callable[[], bool] = lambda: False,
        control: RunControl | None = None,
        on_event: Callable[[dict], None] = lambda e: None,
        ask_to_continue: bool = False,
        probe_limit: int = MAX_CLICK_PROBES,
    ) -> None:
        # ask_to_continue: saat layar habis, tanya QA dulu (lanjutkan memetakan / selesai) sebelum run selesai
        self.ask_to_continue = ask_to_continue and control is not None
        self.probe_limit = probe_limit
        self._probe_cap = probe_limit
        self._depth_cap = max_depth
        self._probed: dict[str, set[tuple[str, str]]] = {}
        self.control = control
        self.on_event = on_event
        self.driver = driver
        self.llm = llm
        self.guard = guard
        self.store = store
        self.auth = auth
        self.start_url = start_url
        self.max_screens = max_screens
        self.max_depth = max_depth
        self.max_minutes = max_minutes
        self.vision = vision
        self.clock = clock
        self.should_stop = should_stop

    def run(self) -> AppMap:
        app_map = AppMap(target=self.start_url)
        deadline = self.clock() + self.max_minutes * 60
        if self.should_stop():
            return app_map
        self.driver.new_session(None)
        self.driver.goto(self.start_url)
        first = self.driver.observe()
        if first.is_login_screen:
            self._add_screen(app_map, first, depth=0, parent=None, public=True)
            if self.auth is None:
                raise LoginFailed("Aplikasi butuh login tetapi akun belum dikonfigurasi")
            self.auth.login()

        visited = {normalize_location(s.url) for s in app_map.screens}
        queue: deque[tuple[str, int, str | None]] = deque([(self.driver.current_url, 0, None)])
        round_no = 0
        while True:
            before = len(app_map.screens)
            self._crawl(app_map, queue, visited, deadline)
            if not self.ask_to_continue or self._exhausted(app_map, deadline):
                break
            if not self._ask(app_map, new_screens=len(app_map.screens) - before if round_no else None):
                break
            # Lanjutkan: coba tombol yang belum dicoba di semua layar, lebih dalam, dan layar yang dibuka QA
            round_no += 1
            self._probe_cap = self.probe_limit * (round_no + 1)
            self._depth_cap = self.max_depth + 2 * round_no
            deadline = self.clock() + self.max_minutes * 60
            self._continue_round(app_map, queue, visited)
        return app_map

    def _ask(self, app_map: AppMap, new_screens: int | None) -> bool:
        """Tanya QA: True = lanjutkan memetakan, False = selesai/dihentikan."""
        assert self.control is not None
        self.control.ask()
        event = {"type": "explore.ask", "screens": len(app_map.screens), "modules": len(app_map.modules())}
        if new_screens is not None:
            event["new_screens"] = new_screens
        for e in (event, {"type": "control.state", "state": "paused", "command": "explore.ask"}):
            try:
                self.on_event(e)
            except Exception:
                pass
        while True:
            d = self.control.wait_before_decide()
            if d.kind == "manual_input":  # QA membuka menu sendiri lewat Ambil alih
                manual = getattr(self.driver, "manual_input", None)
                if manual is not None:
                    manual(d.input or {})
                continue
            if d.kind == "stop" or self.should_stop():
                return False
            return not self.control.take_finish()

    def _continue_round(self, app_map: AppMap, queue: deque, visited: set[str]) -> None:
        # Layar tempat QA berhenti setelah Ambil alih ikut dipetakan
        try:
            here = self.driver.current_url
            if normalize_location(here) not in visited and self.guard.is_allowed_url(here):
                queue.append((here, 1, None))
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception:
            pass
        for screen in list(app_map.screens):
            if self.should_stop():
                return
            if screen.depth >= self._depth_cap:
                continue
            obs = self._open(screen.url)
            if obs is None:
                continue
            for next_url in self._discover(obs, ScreenSummary(), screen.url):
                if normalize_location(next_url) not in visited:
                    queue.append((next_url, screen.depth + 1, screen.fingerprint))

    def _crawl(self, app_map: AppMap, queue: deque, visited: set[str], deadline: float) -> None:
        while queue and not self._exhausted(app_map, deadline):
            self._checkpoint()
            if self.should_stop():
                break
            target, depth, parent = queue.popleft()
            key = normalize_location(target)
            if key in visited or not self.guard.is_allowed_url(target):
                continue
            obs = self._open(target)
            visited.add(key)
            if obs is None:
                continue
            landed = normalize_location(obs.location)
            if landed != key and landed in visited:
                continue  # diarahkan ke layar yang sudah dicatat
            visited.add(landed)
            summary, info = self._add_screen(app_map, obs, depth, parent)
            if depth < self._depth_cap:
                found = self._discover(obs, summary, target)
                if not found and getattr(self.driver, "back_probe", False):
                    # Layar buntu (mis. form popup setelah login): coba Kembali, mungkin ada layar lain di baliknya
                    behind = self._back_probe(target)
                    if behind:
                        found = [behind]
                for next_url in found:
                    if normalize_location(next_url) not in visited:
                        queue.append((next_url, depth + 1, info.fingerprint))

    def _checkpoint(self) -> None:
        """Titik kontrol explore: jeda menahan di sini; input manual saat ambil alih dijalankan."""
        if self.control is None:
            return
        while True:
            d = self.control.wait_before_decide()
            if d.kind != "manual_input":
                return
            manual = getattr(self.driver, "manual_input", None)
            if manual is not None:
                manual(d.input or {})

    def _exhausted(self, app_map: AppMap, deadline: float) -> bool:
        return len(app_map.screens) >= self.max_screens or self.clock() >= deadline or self.should_stop()

    def _open(self, target: str) -> Observation | None:
        try:
            self.driver.goto(target)
            obs = self.driver.observe()
            if obs.is_login_screen and self.auth is not None:
                self.auth.login()  # sesi kedaluwarsa
                self.driver.goto(target)
                obs = self.driver.observe()
                if obs.is_login_screen:
                    return None
            return obs
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception as e:
            self.store.append_step(StepRecord(tc_id="EXPLORE", step_no=0, timestamp=now_iso(), location=target,
                                              action="navigate", value=target, result=f"error: {type(e).__name__}: {e}"))
            return None

    def _summarize(self, obs: Observation, known_modules: list[str]) -> ScreenSummary:
        system = prompts.explore_system(known_modules)
        message = prompts.explore_message(obs, self.vision)
        for _ in range(2):
            try:
                return ScreenSummary.model_validate(extract_json(self.llm.chat(system, [message])))
            except (ActionParseError, ValidationError):
                continue
        links = [e.index for e in obs.elements if e.role == "link"]
        return ScreenSummary(module="Lainnya", page_name=obs.title or obs.location, nav_candidates=links)

    def _add_screen(self, app_map: AppMap, obs: Observation, depth: int, parent: str | None,
                    public: bool = False) -> tuple[ScreenSummary, ScreenInfo]:
        summary = self._summarize(obs, app_map.modules())
        module = app_map.find_module(summary.module) or (" ".join(summary.module.split()) or "Lainnya")
        n = len(app_map.screens) + 1
        shot = self.store.save_screenshot(f"explore_{n:03d}", self.driver.screenshot())
        info = ScreenInfo(
            fingerprint=obs.fingerprint, url=obs.location, module=module,
            page_name=summary.page_name or obs.title or obs.location, purpose=summary.purpose,
            forms=summary.forms, actions=summary.actions, screenshot=shot, depth=depth, parent=parent, public=public,
        )
        path_to = getattr(self.driver, "path_to", None)
        if path_to is not None:  # Android: simpan jalur tap supaya run modul bisa kembali ke layar ini
            info.nav_path = path_to(obs.location)
        app_map.screens.append(info)
        self.store.write_app_map(app_map)
        try:
            self.on_event({"type": "screen.added", "url": info.url, "module": info.module,
                           "page_name": info.page_name, "screenshot": shot})
        except Exception:
            pass
        self.store.append_step(StepRecord(
            tc_id="EXPLORE", step_no=n, timestamp=now_iso(), location=obs.location, fingerprint=obs.fingerprint,
            thought=summary.purpose, action="navigate", value=obs.location, signals=obs.signals, screenshot=shot,
        ))
        return summary, info

    def _discover(self, obs: Observation, summary: ScreenSummary, current: str) -> list[str]:
        by_index = {e.index: e for e in obs.elements}
        found: list[str] = []
        probes: list[tuple[str, str]] = []
        candidates = list(summary.nav_candidates)
        if getattr(self.driver, "back_probe", False):
            # Android: menu berupa tombol/tab, bukan link. Jawaban AI bisa kosong atau tidak lengkap, jadi tombol
            # aman lain di layar tetap dicoba (setelah kandidat dari AI). Guard explore memblok tombol berisiko.
            candidates += [e.index for e in obs.elements
                           if e.role in NAV_ROLES and (e.name or "").strip() and e.index not in candidates]
        for idx in candidates:
            element = by_index.get(idx)
            if element is None:
                continue
            if not self.guard.check(Action(action="click", element=idx), element, explore=True).allowed:
                continue
            if element.href and element.href.startswith(("http://", "https://")):
                found.append(_clean_href(element.href))
            else:
                probes.append((element.role, element.name))
        # Tombol yang sudah pernah dicoba di layar ini tidak dicoba lagi (putaran Lanjutkan memetakan)
        tried = self._probed.setdefault(normalize_location(current), set())
        budget = max(self._probe_cap - len(tried), 0)
        probes = [p for p in dict.fromkeys(probes) if p not in tried][:budget]
        for role, name in probes:
            if self.should_stop():
                break
            tried.add((role, name))
            target = self._click_probe(current, role, name)
            if target:
                found.append(target)
        return found

    def _back_probe(self, current: str) -> str | None:
        try:
            self.driver.goto(current)
            before = normalize_location(self.driver.current_url)
            result = self.driver.execute(Action(action="back"), None)
            after = self.driver.current_url
            if result.ok and normalize_location(after) != before and self.guard.is_allowed_url(after):
                return after
            return None
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception:
            return None

    def _click_probe(self, current: str, role: str, name: str) -> str | None:
        """Klik elemen tanpa href (tab/menu SPA) untuk melihat apakah pindah halaman."""
        try:
            self.driver.goto(current)
            obs = self.driver.observe()
            element = next((e for e in obs.elements if e.role == role and e.name == name), None)
            if element is None:
                return None
            before = normalize_location(self.driver.current_url)
            result = self.driver.execute(Action(action="click", element=element.index), element)
            after = self.driver.current_url
            if result.ok and normalize_location(after) != before and self.guard.is_allowed_url(after):
                return after
            return None
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception:
            return None
