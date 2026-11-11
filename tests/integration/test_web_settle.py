"""Menunggu halaman tenang tidak boleh terjebak polling (dashboard yang terus memanggil server)."""
import time

import pytest

from qa_agent.drivers.web import WebDriver

pytestmark = pytest.mark.browser


@pytest.fixture
def driver(demo):
    d = WebDriver(demo.url, headless=True)
    d.start()
    d.new_session(None)
    yield d
    d.stop()


def test_settle_ignores_endless_polling(driver):
    driver.goto("/login")
    # halaman yang polling ke server tiap 200 ms tanpa henti: networkidle tidak pernah tercapai
    driver.page.evaluate("() => setInterval(() => fetch('/login?poll=' + Date.now()).catch(() => {}), 200)")
    started = time.monotonic()
    driver.observe()
    assert time.monotonic() - started < 2.5  # dulu selalu >= 3 detik (batas networkidle)


def test_settle_waits_for_request_triggered_by_action(driver):
    driver.goto("/login")
    driver.page.evaluate("""() => { window.done = false;
      setTimeout(() => fetch('/login?slow=1').then(() => { document.body.dataset.loaded = '1'; }), 100); }""")
    driver._settle()
    assert driver.page.evaluate("() => document.body.dataset.loaded") == "1"
