from qa_agent.drivers.web import WebDriver, is_benign_js_error, is_tracked_url


def test_tracked_url_only_app_domains():
    # Review #5: 5xx dari pihak ketiga (Sentry, CDN, analytics) bukan bug aplikasi
    assert is_tracked_url("https://app.test/api/users", ["app.test"])
    assert is_tracked_url("https://api.app.test/x", ["app.test"])
    assert not is_tracked_url("https://sentry.io/api/1/envelope", ["app.test"])


def test_benign_js_errors_ignored():
    assert is_benign_js_error("ResizeObserver loop completed with undelivered notifications.")
    assert is_benign_js_error("ResizeObserver loop limit exceeded")
    assert not is_benign_js_error("TypeError: Cannot read properties of undefined")


def test_tracked_domains_default_to_base_host():
    assert WebDriver("http://127.0.0.1:5055").tracked_domains == ["127.0.0.1"]
    assert WebDriver("http://a.test", tracked_domains=["a.test", "b.test"]).tracked_domains == ["a.test", "b.test"]
