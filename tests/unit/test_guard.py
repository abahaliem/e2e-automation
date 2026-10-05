from qa_agent.guard import Guard
from qa_agent.models import Action, Element

DEV = Guard("dev", ["app.test"])
PROD = Guard("production", ["app.test"])


def el(name, role="button", context="", href=None):
    return Element(index=1, role=role, name=name, context=context, href=href)


def click(risk="low"):
    return Action(action="click", element=1, risk=risk)


def test_dev_allows_risky_click():
    assert DEV.check(click(), el("Hapus")).allowed


def test_production_blocks_keyword():
    d = PROD.check(click(), el("Hapus Pengguna"))
    assert not d.allowed and d.risk == "high" and "production" in d.reason


def test_production_keyword_in_form_context():
    assert not PROD.check(click(), el("OK", context="Konfirmasi Transfer")).allowed


def test_keyword_whole_word_only():
    assert PROD.check(click(), el("Unsaved draft list")).allowed
    assert PROD.check(click(), el("Updated at")).allowed


def test_ai_cannot_downgrade_risk():
    assert not PROD.check(click(risk="low"), el("Simpan")).allowed


def test_ai_high_risk_blocks_without_keyword():
    assert not PROD.check(click(risk="high"), el("Proses")).allowed
    assert DEV.check(click(risk="high"), el("Proses")).allowed


def test_typing_is_not_keyword_checked():
    action = Action(action="type", element=1, value="catatan")
    assert PROD.check(action, el("Catatan", role="input", context="Update Profil")).allowed


def test_logout_blocked_unless_allowed():
    assert not DEV.check(click(), el("Keluar")).allowed
    assert not DEV.check(click(), el("Log out")).allowed
    assert DEV.check(click(), el("Keluar"), allow_logout=True).allowed


def test_external_link_blocked_subdomain_allowed():
    assert not DEV.check(click(), el("Docs", role="link", href="https://evil.example/x")).allowed
    assert DEV.check(click(), el("API", role="link", href="https://api.app.test/x")).allowed


def test_javascript_link_treated_as_same_page():
    assert DEV.check(click(), el("Tab", role="link", href="javascript:void(0)")).allowed


def test_mailto_link_blocked():
    assert not DEV.check(click(), el("Email kami", role="link", href="mailto:a@b.c")).allowed


def test_navigate_domain_check():
    assert not DEV.check(Action(action="navigate", value="https://other.test/"), None).allowed
    assert DEV.check(Action(action="navigate", value="/users"), None).allowed
    assert not DEV.check(Action(action="navigate", value=None), None).allowed


def test_explore_is_navigation_only():
    assert not DEV.check(Action(action="type", element=1, value="x"), el("Cari", role="input"), explore=True).allowed
    assert not DEV.check(click(), el("Hapus"), explore=True).allowed
    assert DEV.check(click(), el("Pengguna", role="link"), explore=True).allowed


def test_login_flow_skips_keyword_rule():
    assert PROD.check(click(), el("Submit"), login=True).allowed


def test_extra_keywords():
    g = Guard("production", ["app.test"], extra_keywords=["Arsipkan"])
    assert not g.check(click(), el("Arsipkan")).allowed


def test_should_block_request_production_only():
    assert PROD.should_block_request("POST", "https://app.test/api/users")
    assert PROD.should_block_request("delete", "https://app.test/api/users/1")
    assert not PROD.should_block_request("GET", "https://app.test/api/users")
    assert not PROD.should_block_request("POST", "https://app.test/login")
    assert not PROD.should_block_request("POST", "https://app.test/api/auth/token")
    assert not DEV.should_block_request("POST", "https://app.test/api/users")


def test_custom_login_endpoints_replace_heuristic():
    g = Guard("production", ["app.test"], login_endpoints=["/api/v2/masuk"])
    assert not g.should_block_request("POST", "https://app.test/api/v2/masuk")
    assert g.should_block_request("POST", "https://app.test/login")
