import pytest

from qa_agent.drivers.web import WebDriver
from qa_agent.guard import Guard
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.helpers import find, login_direct

pytestmark = pytest.mark.browser


def center(driver, element):
    x, y, w, h = element.bbox
    vw, vh = driver.viewport
    return {"kind": "click", "x": (x + w / 2) / vw, "y": (y + h / 2) / vh}


def test_manual_login_with_normalized_click(demo):
    d = WebDriver(demo.url, headless=True)
    d.start()
    try:
        d.new_session(None)
        d.goto("/login")
        obs = d.observe()
        assert d.manual_input(center(d, find(obs, "input", "Email"))).ok
        assert d.manual_input({"kind": "type", "text": DEMO_USER}).ok
        assert d.manual_input(center(d, find(obs, "input", "Password"))).ok
        assert d.manual_input({"kind": "type", "text": DEMO_PASSWORD}).ok
        assert d.manual_input(center(d, find(obs, "button", "Masuk"))).ok
        assert not d.observe().is_login_screen
        assert d.manual_input({"kind": "scroll", "dy": 300}).ok
        assert d.manual_input({"kind": "key", "key": "Tab"}).ok
        assert d.viewport_size() == {"width": 1366, "height": 768}
    finally:
        d.stop()


def test_manual_input_rejects_bad_event(demo):
    d = WebDriver(demo.url, headless=True)
    d.start()
    try:
        d.new_session(None)
        d.goto("/login")
        assert not d.manual_input({"kind": "click", "x": "abc", "y": 0.5}).ok
        assert not d.manual_input({"kind": "terbang"}).ok
    finally:
        d.stop()


def test_production_filter_still_applies_to_manual_click(demo):
    guard = Guard("production", ["127.0.0.1"])
    d = WebDriver(demo.url, headless=True, request_filter=guard.should_block_request)
    d.start()
    try:
        d.new_session(None)
        d.login_mode = True
        login_direct(d)
        d.login_mode = False
        d.goto("/reports")
        result = d.manual_input(center(d, find(d.observe(), "button", "Proses Ulang")))
        assert not result.fatal
        assert demo.state.writes == []
        assert any("/reports/rebuild" in r for r in d.blocked_requests)
    finally:
        d.stop()
