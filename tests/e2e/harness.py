"""Dashboard sungguhan + AI palsu (DemoBrain) untuk test E2E dan screenshot.

Hanya untuk test/dev: `llm_factory` tidak bisa diaktifkan dari `qa-agent serve`.
Jalankan manual: `python -m tests.e2e.harness` (dashboard + aplikasi demo, data di folder sementara).
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from qa_agent.llm.fake import FakeLLM
from qa_agent.server.app import STATIC_DIR, create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from tests.integration.brain import DemoBrain


def slow_brain(delay: float):
    """DemoBrain dengan jeda per jawaban supaya ada waktu untuk menonton/mengintervensi."""

    def factory(profile):
        brain = DemoBrain()

        def respond(system, messages):
            time.sleep(delay)
            return brain(system, messages)

        return FakeLLM(respond)

    return factory


class DashboardServer:
    def __init__(self, data_dir: Path, port: int, delay: float = 0.4) -> None:
        self.settings = ServerSettings(data_dir=data_dir, port=port)
        self.app = create_app(self.settings, secrets=MemorySecretStore(), llm_factory=slow_brain(delay))
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def start(self) -> "DashboardServer":
        self._thread.start()
        deadline = time.monotonic() + 20
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Dashboard tidak bisa dijalankan")
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(15)


def frontend_built() -> bool:
    return (STATIC_DIR / "index.html").is_file()


if __name__ == "__main__":
    from qa_agent.cli import find_free_port
    from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, DemoServer

    demo = DemoServer().start()
    data = Path(tempfile.mkdtemp(prefix="qa-agent-demo-"))
    server = DashboardServer(data, find_free_port(8787), delay=0.8).start()
    print(f"Dashboard     : {server.url}")
    print(f"Aplikasi demo : {demo.url}  (akun {DEMO_USER} / {DEMO_PASSWORD})")
    print(f"Folder data   : {data}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        demo.stop()
