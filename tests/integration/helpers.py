from qa_agent.models import Element, Observation
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER


def find(obs: Observation, role: str, name: str) -> Element:
    for e in obs.elements:
        if e.role == role and e.name == name:
            return e
    raise AssertionError(f"{role} '{name}' tidak ada. Elemen: {[(e.role, e.name) for e in obs.elements]}")


def login_direct(driver) -> None:
    """Login lewat Playwright langsung (untuk test yang bukan tentang execute)."""
    driver.goto("/login")
    driver.page.fill("#email", DEMO_USER)
    driver.page.fill("#password", DEMO_PASSWORD)
    driver.page.click("button[type=submit]")
    driver.page.wait_for_load_state("domcontentloaded")
