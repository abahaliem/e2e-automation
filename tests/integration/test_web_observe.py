from urllib.parse import urlsplit

import pytest

from qa_agent.drivers.base import DriverCrashed
from qa_agent.drivers.web import WebDriver
from tests.integration.helpers import find, login_direct

pytestmark = pytest.mark.browser


@pytest.fixture
def driver(demo):
    d = WebDriver(demo.url, headless=True)
    d.start()
    d.new_session(None)
    yield d
    d.stop()


def test_observe_login_page(driver, demo):
    driver.goto("/users")  # belum login → diarahkan ke /login
    obs = driver.observe()
    assert "/login" in obs.location and obs.is_login_screen
    email = find(obs, "input", "Email")
    password = find(obs, "input", "Password")
    button = find(obs, "button", "Masuk")
    assert password.input_type == "password"
    assert email.selector == '[id="email"]'
    assert button.selector == 'role=button[name="Masuk"]'
    assert button.context == "Masuk"
    assert [e.index for e in obs.elements] == list(range(1, len(obs.elements) + 1))
    assert obs.screenshot_annotated[:8] == b"\x89PNG\r\n\x1a\n"
    assert obs.fingerprint.startswith(f"{urlsplit(demo.url).netloc}/login|")


def test_users_page_elements(driver):
    login_direct(driver)
    driver.goto("/users")
    obs = driver.observe()
    names = [(e.role, e.name) for e in obs.elements]
    assert ("link", "Tambah Pengguna") in names
    assert ("button", "Ekspor") in names
    assert ("button", "Keluar") in names
    assert names.count(("link", "Edit")) == 2
    assert names.count(("button", "Hapus")) == 2
    edit = find(obs, "link", "Edit")
    assert edit.href.endswith("/users/1/edit")


def test_form_context_and_values(driver):
    login_direct(driver)
    driver.goto("/users/new")
    obs = driver.observe()
    assert find(obs, "button", "Simpan").context == "Tambah Pengguna"
    assert find(obs, "input", "Nama").value == ""


def test_http_500_signal(driver):
    login_direct(driver)
    driver.goto("/users/new")
    driver.observe()
    driver.page.fill("#name", "O'Brien")
    driver.page.fill("#age", "3")
    driver.page.click("text=Simpan")
    obs = driver.observe()
    errors = [s for s in obs.signals if s.kind == "http_error"]
    assert any(s.status == 500 and s.method == "POST" for s in errors)


def test_ui_error_signal(driver):
    login_direct(driver)
    driver.goto("/users/new")
    driver.observe()
    driver.page.fill("#age", "3")
    driver.page.click("text=Simpan")
    obs = driver.observe()
    assert any(s.kind == "ui_error" and "Nama wajib diisi" in s.message for s in obs.signals)
    assert any(s.kind == "http_error" and s.status == 400 for s in obs.signals)


def test_transient_error_toast_photographed_when_it_appears(driver):
    """Toast error yang hilang sebelum agent melihat layar tetap tercatat, lengkap dengan foto saat muncul."""
    driver.goto("/login")
    driver.observe()
    driver.page.evaluate("""() => {
      const t = document.createElement('div');
      t.className = 'toast toast-error';
      t.textContent = 'Gagal menyimpan data: server error';
      t.style.cssText = 'position:fixed;top:10px;right:10px;padding:12px;background:#c00;color:#fff';
      document.body.appendChild(t);
      setTimeout(() => t.remove(), 600);
    }""")
    for _ in range(24):  # seperti saat menunggu jawaban AI: driver dipompa tiap 50 ms
        driver.pump(50)
    assert driver.page.locator(".toast").count() == 0  # toast sudah hilang
    obs = driver.observe()
    sig = next(s for s in obs.signals if s.kind == "ui_error" and "Gagal menyimpan data" in s.message)
    assert sig.message.startswith("Pesan muncul sesaat lalu hilang") and sig.at
    assert obs.evidence[sig.message][:8] == b"\x89PNG\r\n\x1a\n"
    assert not any("Gagal menyimpan" in s.message for s in driver.observe().signals)  # dilaporkan sekali


def test_visible_ui_error_has_evidence(driver):
    login_direct(driver)
    driver.goto("/users/new")
    driver.observe()
    driver.page.fill("#age", "3")
    driver.page.click("text=Simpan")
    obs = driver.observe()
    sig = next(s for s in obs.signals if s.kind == "ui_error" and "Nama wajib diisi" in s.message)
    assert obs.evidence[sig.message][:8] == b"\x89PNG\r\n\x1a\n"
    assert sum(1 for s in obs.signals if "Nama wajib diisi" in s.message) == 1  # tidak dobel dari pemantau


def test_auth_state_roundtrip(driver, tmp_path):
    login_direct(driver)
    state = tmp_path / "auth" / "state.json"
    driver.save_auth_state(state)
    driver.new_session(state)
    driver.goto("/users")
    assert driver.current_url.endswith("/users")
    assert not driver.observe().is_login_screen


def test_screenshot_with_highlight(driver):
    driver.goto("/login")
    obs = driver.observe()
    png = driver.screenshot(highlight=find(obs, "button", "Masuk"))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_closed_driver_raises_crash(driver):
    driver.stop()
    with pytest.raises(DriverCrashed):
        driver.observe()
