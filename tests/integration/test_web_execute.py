import pytest

from qa_agent.drivers.web import WebDriver
from qa_agent.guard import Guard
from qa_agent.models import Action
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.helpers import find

pytestmark = pytest.mark.browser


def make(demo, **kw):
    d = WebDriver(demo.url, headless=True, **kw)
    d.start()
    d.new_session(None)
    d.set_credentials(DEMO_USER, DEMO_PASSWORD)
    return d


def login(d):
    d.goto("/login")
    obs = d.observe()
    assert d.execute(Action(action="type", value="{{username}}"), find(obs, "input", "Email")).ok
    assert d.execute(Action(action="type", value="{{password}}"), find(obs, "input", "Password")).ok
    assert d.execute(Action(action="click"), find(obs, "button", "Masuk")).ok


@pytest.fixture
def driver(demo):
    d = make(demo)
    yield d
    d.stop()


def test_login_with_placeholders(driver):
    login(driver)
    obs = driver.observe()
    assert not obs.is_login_screen
    find(obs, "link", "Pengguna")


def test_password_value_not_exposed(driver):
    driver.goto("/login")
    obs = driver.observe()
    driver.execute(Action(action="type", value="{{password}}"), find(obs, "input", "Password"))
    after = driver.observe()
    assert find(after, "input", "Password").value == "******"
    assert DEMO_PASSWORD not in after.model_dump_json(exclude={"screenshot_annotated"})


def test_navigate_back_scroll_wait(driver):
    login(driver)
    assert driver.execute(Action(action="navigate", value="/reports"), None).ok
    assert driver.current_url.endswith("/reports")
    assert driver.execute(Action(action="back"), None).ok
    assert not driver.current_url.endswith("/reports")
    assert driver.execute(Action(action="scroll", value="down"), None).ok
    assert driver.execute(Action(action="wait", value="0.1"), None).ok


def test_click_requires_element(driver):
    result = driver.execute(Action(action="click"), None)
    assert not result.ok and "butuh elemen" in result.error


def test_password_placeholder_only_fills_password_fields(driver):
    # Review #6: {{password}} tidak boleh diisi ke field biasa (akan terlihat di layar & laporan)
    driver.goto("/login")
    obs = driver.observe()
    driver.execute(Action(action="type", value="{{password}}"), find(obs, "input", "Email"))
    assert find(driver.observe(), "input", "Email").value == "{{password}}"


# Dengan service_workers="block", Playwright membuat register() resolve ke undefined dan sw.js tidak pernah diambil.
SW_JS = "async () => { try { const r = await navigator.serviceWorker.register('/sw.js'); return r ? 'ok' : 'blocked'; } catch (e) { return 'blocked'; } }"


def test_service_workers_blocked_in_production(demo):
    # Review #2: request dari Service Worker tidak melewati context.route, jadi SW harus diblok
    dev = make(demo)
    try:
        dev.goto("/login")
        assert dev.page.evaluate(SW_JS) == "ok"
    finally:
        dev.stop()
    prod = make(demo, request_filter=Guard("production", ["127.0.0.1"]).should_block_request)
    try:
        prod.goto("/login")
        assert prod.page.evaluate(SW_JS) == "blocked"
    finally:
        prod.stop()


def test_stale_element_returns_error_not_crash(demo):
    d = make(demo, action_timeout_ms=1500)
    try:
        login(d)
        d.goto("/users")
        stale = find(d.observe(), "link", "Tambah Pengguna")
        d.goto("/reports")
        d.observe()  # data-qa-idx di halaman baru tidak memiliki elemen tadi
        stale = stale.model_copy(update={"index": 999})
        result = d.execute(Action(action="click"), stale)
        assert not result.ok and not result.fatal
    finally:
        d.stop()


def test_production_filter_blocks_writes_but_allows_login(demo):
    guard = Guard("production", ["127.0.0.1"])
    d = make(demo, request_filter=guard.should_block_request)
    try:
        d.login_mode = True  # endpoint login hanya dibuka selama alur login (review #3)
        login(d)
        d.login_mode = False
        assert not d.observe().is_login_screen  # POST /login diizinkan
        d.goto("/reports")
        result = d.execute(Action(action="click"), find(d.observe(), "button", "Proses Ulang"))
        assert not result.fatal  # navigasi yang dibatalkan boleh dilaporkan gagal, tapi browser tetap hidup
        assert demo.state.writes == []
        assert any("/reports/rebuild" in r for r in d.blocked_requests)
        assert any(s.kind == "blocked_request" for s in d.observe().signals)
    finally:
        d.stop()


def test_fatal_when_browser_closed(demo):
    d = make(demo)
    d.goto("/login")
    obs = d.observe()
    d._browser.close()
    result = d.execute(Action(action="click"), find(obs, "button", "Masuk"))
    assert not result.ok and result.fatal
    d.stop()
