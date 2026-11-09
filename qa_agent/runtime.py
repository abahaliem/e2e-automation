from __future__ import annotations

import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from qa_agent.agent.control import RunControl
from qa_agent.agent.loop import AgentLoop
from qa_agent.config import Config, Credentials
from qa_agent.drivers.web import WebDriver
from qa_agent.evidence import Masker, RunStore
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient
from qa_agent.llm.factory import build_llm
from qa_agent.orchestrator.auth import AuthManager, auth_state_path
from qa_agent.orchestrator.deep import DeepPlanner, DeepRunner
from qa_agent.orchestrator.explore import Explorer


class StopFlag:
    """Ctrl+C pertama: selesaikan langkah berjalan lalu berhenti. Ctrl+C kedua: keluar paksa."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def __call__(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()

    def install(self) -> None:
        def handler(signum, frame):
            self.set()
            signal.signal(signal.SIGINT, signal.default_int_handler)
            print("\nCtrl+C diterima: menyelesaikan langkah berjalan lalu menulis laporan. "
                  "Tekan Ctrl+C lagi untuk keluar paksa.", file=sys.stderr)

        signal.signal(signal.SIGINT, handler)


@dataclass
class Runtime:
    cfg: Config
    store: RunStore
    environment: str
    driver: Any  # WebDriver atau AndroidDriver
    llm: LLMClient
    guard: Guard
    masker: Masker
    stop: StopFlag
    loop: AgentLoop
    auth: AuthManager
    data_prefix: str
    control: RunControl | None = None
    on_event: Callable[[dict], None] = lambda e: None


def build_runtime(cfg: Config, store: RunStore, project_dir: Path, *, environment: str,
                  llm: LLMClient | None = None, now: datetime | None = None,
                  credentials: Credentials | None = None, api_key: str | None = None,
                  control: RunControl | None = None, on_event: Callable[[dict], None] | None = None,
                  auth_state: Path | None = None, device_serial: str | None = None) -> Runtime:
    """Parameter eksplisit (kredensial, API key, control, on_event) dipakai dashboard; CLI membaca environment."""
    guard = Guard(environment, cfg.domains(), extra_keywords=cfg.guard.extra_risky_keywords,
                  login_endpoints=cfg.target.login_endpoints)
    creds = credentials or cfg.credentials()
    masker = Masker([creds.password])
    if cfg.target.platform == "android":
        from qa_agent.drivers.adb import Adb
        from qa_agent.drivers.android import AndroidDriver

        driver = AndroidDriver(Adb(serial=device_serial), cfg.target.package)
    else:
        driver = WebDriver(cfg.target.url, headless=cfg.browser.headless, viewport=cfg.browser.size,
                           request_filter=guard.should_block_request if guard.production else None,
                           tracked_domains=cfg.domains())
    driver.set_credentials(creds.username, creds.password)
    stop = StopFlag()
    data_prefix = f"QA-AUTO-{(now or datetime.now()):%Y%m%d-%H%M}"
    llm = llm or build_llm(cfg, api_key)
    emit = on_event or (lambda e: None)
    common = dict(driver=driver, llm=llm, guard=guard, store=store, masker=masker, data_prefix=data_prefix,
                  max_steps=cfg.limits.max_steps_per_tc, vision=cfg.llm.vision, should_stop=stop,
                  platform=cfg.target.platform,
                  control=control, on_event=emit)
    login_loop = AgentLoop(**common)

    def run_login(tc_id: str, goal: str):
        driver.login_mode = True  # endpoint login hanya dibuka selama alur login
        try:
            return login_loop.run(tc_id, goal, login=True)
        finally:
            driver.login_mode = False

    auth = AuthManager(driver, run_login,
                       auth_state or auth_state_path(project_dir, cfg.target.url, creds.role), creds.role)
    return Runtime(cfg=cfg, store=store, environment=environment, driver=driver, llm=llm, guard=guard, masker=masker,
                   stop=stop, loop=AgentLoop(**common), auth=auth, data_prefix=data_prefix, control=control,
                   on_event=emit)


def _should_stop(rt: Runtime) -> Callable[[], bool]:
    control = rt.control
    if control is None:
        return rt.stop
    return lambda: rt.stop() or control.state == "stopped"


def make_explorer(rt: Runtime) -> Explorer:
    limits = rt.cfg.limits
    return Explorer(driver=rt.driver, llm=rt.llm, guard=rt.guard, store=rt.store, auth=rt.auth,
                    start_url=rt.cfg.target.url, max_screens=limits.explore_max_screens,
                    max_depth=limits.explore_max_depth, max_minutes=limits.explore_max_minutes,
                    vision=rt.cfg.llm.vision, should_stop=_should_stop(rt), control=rt.control,
                    on_event=rt.on_event)


def make_planner(rt: Runtime) -> DeepPlanner:
    return DeepPlanner(rt.llm, data_prefix=rt.data_prefix, max_tcs=rt.cfg.limits.deep_max_tcs)


def make_runner(rt: Runtime) -> DeepRunner:
    return DeepRunner(driver=rt.driver, loop=rt.loop, auth=rt.auth, store=rt.store, should_stop=_should_stop(rt),
                      on_event=rt.on_event)
