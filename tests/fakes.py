"""Driver & data palsu untuk unit test (tanpa browser)."""
from __future__ import annotations

import json
from pathlib import Path

from qa_agent.imaging import solid_png
from qa_agent.models import Action, ActionResult, Element, Observation, Signal
from qa_agent.orchestrator.fingerprint import fingerprint

PNG = solid_png((255, 255, 255), (16, 12))
BASE = "http://app.test"


def url(path: str) -> str:
    return f"{BASE}/{path.lstrip('/')}"


def el(index: int, role: str, name: str, **kw) -> Element:
    kw.setdefault("bbox", (1.0, 1.0, 10.0, 5.0))
    kw.setdefault("selector", f"{role}:{name}")
    return Element(index=index, role=role, name=name, **kw)


def screen(path: str, *elements: Element, title: str | None = None, signals: tuple[Signal, ...] = ()) -> Observation:
    location = url(path)
    items = list(elements)
    return Observation(location=location, title=title or path, elements=items, signals=list(signals),
                       screenshot_annotated=PNG, fingerprint=fingerprint(location, items))


def act(**kw) -> str:
    return json.dumps(kw)


class FakeDriver:
    """Layar terskrip. transitions: {(lokasi_sekarang, nama_elemen_atau_aksi): lokasi_berikut}."""

    def __init__(self, screens: list[Observation], start: str, transitions: dict | None = None, *,
                 fail_first: int = 0, fatal: bool = False) -> None:
        self.screens = {s.location: s for s in screens}
        self.current = start
        self.transitions = transitions or {}
        self.fail_first = fail_first
        self.fatal = fatal
        self.executed: list[tuple[str, str | None, str | None]] = []
        self.gotos: list[str] = []
        self.sessions: list = []
        self.saved: list[Path] = []
        self.credentials: dict[str, str] = {}
        self.started = False
        self.manual: list[dict] = []
        self.manual_result = ActionResult(ok=True)

    def manual_input(self, event: dict) -> ActionResult:
        self.manual.append(dict(event))
        return self.manual_result

    def viewport_size(self) -> dict:
        return {"width": 1366, "height": 768}

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def new_session(self, auth_state=None) -> None:
        self.sessions.append(auth_state)

    def save_auth_state(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        self.saved.append(path)

    def goto(self, location: str) -> None:
        self.gotos.append(location)
        if location not in self.screens:
            raise RuntimeError(f"FakeDriver: layar {location} tidak ada")
        self.current = location

    @property
    def current_url(self) -> str:
        return self.current

    def set_credentials(self, username: str, password: str) -> None:
        self.credentials = {"{{username}}": username, "{{password}}": password}

    def observe(self) -> Observation:
        return self.screens[self.current].model_copy(deep=True)

    def screenshot(self, highlight=None) -> bytes:
        return PNG

    def execute(self, action: Action, element: Element | None) -> ActionResult:
        if self.fatal:
            return ActionResult(ok=False, error="Target closed", fatal=True)
        if self.fail_first > 0:
            self.fail_first -= 1
            return ActionResult(ok=False, error="Element is not attached to the DOM")
        value = action.value
        if value:
            for placeholder, real in self.credentials.items():
                value = value.replace(placeholder, real)
        name = element.name if element else None
        self.executed.append((action.action, name, value))
        nxt = self.transitions.get((self.current, name or action.action))
        if nxt:
            self.current = nxt
        return ActionResult(ok=True)
