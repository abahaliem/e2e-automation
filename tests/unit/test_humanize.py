from qa_agent.models import Signal
from qa_agent.report.humanize import humanize, signal_text


def test_humanize_actions():
    btn = {"role": "button", "name": "Simpan"}
    field = {"role": "input", "name": "Email"}
    assert humanize("click", btn, None) == "Klik tombol 'Simpan'"
    assert humanize("type", field, "bukan-email") == "Isi field 'Email' dengan 'bukan-email'"
    assert humanize("type", field, "") == "Kosongkan field 'Email'"
    assert humanize("select", {"role": "select", "name": "Kota"}, "Bandung") == "Pilih 'Bandung' pada dropdown 'Kota'"
    assert humanize("scroll", None, "up") == "Gulir halaman ke atas"
    assert humanize("navigate", None, "/users") == "Buka halaman /users"
    assert humanize("blocked", None, "tombol tidak ada") == "Tidak bisa dilanjutkan: tombol tidak ada"
    assert humanize("click", {"role": "div", "name": ""}, None) == "Klik elemen 'tanpa nama'"


def test_signal_text():
    assert signal_text(Signal(kind="http_error", message="x", status=500, method="POST", url="http://a/users")) == "HTTP 500 POST http://a/users"
    assert signal_text(Signal(kind="page_error", message="TypeError: x")) == "Error JavaScript: TypeError: x"
    assert signal_text(Signal(kind="blocked_request", message="x", method="POST", url="http://a/r")) == "Request diblok: POST http://a/r"
