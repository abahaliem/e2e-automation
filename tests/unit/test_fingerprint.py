from qa_agent.models import Element
from qa_agent.orchestrator.fingerprint import fingerprint, normalize_location


def els(*names):
    return [Element(index=i, role="link", name=n) for i, n in enumerate(names, 1)]


def test_numeric_ids_normalized():
    assert normalize_location("https://App.test/users/123/edit") == "app.test/users/:id/edit"


def test_uuid_and_long_hex_normalized():
    assert normalize_location("https://a.test/o/3f2a1b4c-1d2e-4f3a-9b8c-0123456789ab") == "a.test/o/:id"
    assert normalize_location("https://a.test/doc/5f8d0d55b54764421b7156c3") == "a.test/doc/:id"


def test_query_dropped_and_trailing_slash():
    assert normalize_location("https://a.test/users/?page=2") == "a.test/users"
    assert normalize_location("https://a.test/") == "a.test/"


def test_hash_route_kept_and_normalized():
    assert normalize_location("https://a.test/#/users/7?x=1") == "a.test/#/users/:id"


def test_non_url_passthrough():
    assert normalize_location("MainActivity") == "MainActivity"


def test_fingerprint_order_insensitive():
    assert fingerprint("https://a.test/x", els("A", "B")) == fingerprint("https://a.test/x", els("B", "A"))


def test_fingerprint_changes_with_elements():
    assert fingerprint("https://a.test/x", els("A")) != fingerprint("https://a.test/x", els("A", "B"))


def test_fingerprint_format():
    fp = fingerprint("https://a.test/users/9", els("Edit"))
    loc, digest = fp.split("|")
    assert loc == "a.test/users/:id" and len(digest) == 8
