"""Screenshot halaman dashboard sungguhan (data demo) ke docs/design/screens/.

Jalankan: `python -m tests.e2e.screens` (butuh `npm --prefix web run build` lebih dulu).
"""
from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from qa_agent.cli import find_free_port
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, DemoServer
from tests.e2e.harness import DashboardServer, frontend_built

OUT = Path(__file__).resolve().parents[2] / "docs" / "design" / "screens"


def wait_status(client: httpx.Client, run_id: int, status: str, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == status:
            return
        time.sleep(0.3)
    raise TimeoutError(f"run {run_id} tidak mencapai status {status}")


def main() -> None:
    if not frontend_built():
        raise SystemExit("Frontend belum di-build: npm --prefix web run build")
    OUT.mkdir(parents=True, exist_ok=True)
    demo = DemoServer().start()
    server = DashboardServer(Path(tempfile.mkdtemp(prefix="qa-agent-shots-")), find_free_port(8795), delay=0.3).start()
    client = httpx.Client(base_url=server.url, timeout=30)
    try:
        client.post("/api/profiles", json={"name": "AI kantor (GLM)", "provider": "openai_compatible",
                                           "base_url": "http://192.168.151.121/v1", "model": "z-ai/glm-5.3-flash",
                                           "api_key": "sk-demo-00003f9a", "is_default": True}).raise_for_status()
        client.post("/api/profiles", json={"name": "Claude", "provider": "anthropic", "model": "claude-sonnet-5-5",
                                           "api_key": "sk-ant-demo-1234"}).raise_for_status()
        app = client.post("/api/apps", json={"name": "Web HR (demo)", "url": demo.url,
                                             "allowed_domains": ["127.0.0.1"]}).json()
        account = client.post(f"/api/apps/{app['id']}/accounts",
                              json={"role": "admin", "username": DEMO_USER, "password": DEMO_PASSWORD}).json()
        run = client.post("/api/runs", json={"app_id": app["id"], "mode": "explore", "account_id": account["id"]}).json()
        wait_status(client, run["id"], "completed")
        deep = client.post("/api/runs", json={"app_id": app["id"], "mode": "deep", "module": "Pengguna",
                                              "account_id": account["id"]}).json()
        wait_status(client, deep["id"], "completed")
        client.patch(f"/api/runs/{deep['id']}/cases/TC-PEN-003",
                     json={"status_final": "Fail", "severity": "Major", "reviewer_note": "Bug valid, nama bertanda petik umum."})
        live = client.post("/api/runs", json={"app_id": app["id"], "mode": "deep", "module": "Pengguna",
                                              "account_id": account["id"], "confirm_each_step": True}).json()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})

            def shot(name: str, full: bool = True) -> None:
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
                print(OUT / f"{name}.png")

            page.goto(f"{server.url}/runs/{live['id']}")
            expect(page.get_by_alt_text("Tampilan langsung browser yang sedang diuji agent")).to_have_attribute(
                "src", re.compile("^blob:"), timeout=60_000)
            expect(page.get_by_role("button", name="Jalankan langkah")).to_be_visible(timeout=60_000)
            page.get_by_role("button", name="Jalankan langkah").click()
            expect(page.get_by_role("button", name="Jalankan langkah")).to_be_visible(timeout=60_000)
            page.get_by_role("button", name="Jalankan langkah").click()
            expect(page.get_by_role("button", name="Jalankan langkah")).to_be_visible(timeout=60_000)
            shot("03-run-berjalan", full=False)

            page.goto(server.url)
            expect(page.get_by_role("link", name="Lihat live")).to_be_visible()
            shot("05-dashboard")

            page.goto(f"{server.url}/runs/new?app={app['id']}")
            expect(page.get_by_label("URL aplikasi")).to_have_value(demo.url)
            shot("01-run-baru-web")

            page.goto(f"{server.url}/settings")
            expect(page.get_by_text("sk-••••3f9a")).to_be_visible()
            shot("04-pengaturan-ai")

            page.goto(f"{server.url}/runs/{deep['id']}/result")
            page.get_by_role("table").get_by_text("Nama dengan apostrof").click()
            expect(page.get_by_role("region", name="Detail test case").get_by_text("TC-PEN-003")).to_be_visible()
            shot("07-hasil-run")

            page.goto(f"{server.url}/apps")
            shot("10-aplikasi")
            page.goto(f"{server.url}/runs")
            shot("11-riwayat")

            client.post(f"/api/runs/{live['id']}/control", json={"command": "stop"})
            browser.close()
    finally:
        client.close()
        server.stop()
        demo.stop()


if __name__ == "__main__":
    main()
