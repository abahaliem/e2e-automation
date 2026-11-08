import pytest
from playwright.sync_api import sync_playwright

from qa_agent.cli import find_free_port
from tests.e2e.harness import DashboardServer, frontend_built


@pytest.fixture
def dashboard(demo, tmp_path):
    if not frontend_built():
        pytest.skip("Frontend belum di-build: jalankan `npm --prefix web install && npm --prefix web run build`")
    server = DashboardServer(tmp_path / "data", find_free_port(8790), delay=0.4).start()
    yield server
    server.stop()


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        pg = context.new_page()
        pg.set_default_timeout(30_000)
        yield pg
        context.close()
        browser.close()
