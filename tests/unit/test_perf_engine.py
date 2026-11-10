"""Mesin uji beban: virtual user konkuren, ramp-up, statistik latency, ambang lulus, berhenti di tengah."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qa_agent.perf.engine import PerfProfile, PerfRequest, Thresholds, parse_curl, percentile, run_load


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/slow"):
            time.sleep(0.05)
        status = 500 if self.path.startswith("/err") else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.send_response(201 if body and self.headers.get("X-Token") == "rahasia" else 400)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_percentile():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50 and percentile(values, 95) == 95 and percentile(values, 99) == 99
    assert percentile([], 95) == 0


def test_load_collects_stats_and_passes_thresholds(server):
    ticks = []
    result = run_load([PerfRequest(name="Daftar WO", method="GET", url=f"{server}/ok", weight=3),
                       PerfRequest(name="Detail lambat", method="GET", url=f"{server}/slow", weight=1)],
                      PerfProfile(vus=5, duration_s=1.5, ramp_up_s=0.5),
                      Thresholds(p95_ms=2000, error_rate_pct=1), on_tick=ticks.append)
    s = result["summary"]
    assert s["total"] > 20 and s["errors"] == 0 and s["rps"] > 0
    assert 0 < s["p50_ms"] <= s["p95_ms"] <= s["max_ms"]
    names = {r["name"]: r for r in result["requests"]}
    assert names["Daftar WO"]["count"] > names["Detail lambat"]["count"]  # bobot 3 : 1
    assert names["Detail lambat"]["p50_ms"] >= 45
    assert result["status_codes"] == {"200": s["total"]}
    assert result["verdict"]["passed"] is True and len(result["verdict"]["checks"]) == 2
    assert ticks and ticks[-1]["elapsed_s"] > 0 and "rps" in ticks[-1] and result["timeline"]
    assert max(t["vus"] for t in result["timeline"]) == 5


def test_errors_and_failed_thresholds(server):
    result = run_load([PerfRequest(name="Error", method="GET", url=f"{server}/err")],
                      PerfProfile(vus=2, duration_s=0.6), Thresholds(p95_ms=0.001, error_rate_pct=5))
    assert result["summary"]["error_rate_pct"] == 100
    assert result["status_codes"] == {"500": result["summary"]["total"]}
    checks = {c["name"]: c for c in result["verdict"]["checks"]}
    assert result["verdict"]["passed"] is False and not checks["Error rate"]["passed"]


def test_expect_status_headers_and_body(server):
    ok = PerfRequest(name="Buat", method="POST", url=f"{server}/wo", headers={"X-Token": "rahasia"}, body='{"a":1}',
                     expect_status=201)
    bad = PerfRequest(name="Tanpa token", method="POST", url=f"{server}/wo", body='{"a":1}', expect_status=201)
    result = run_load([ok, bad], PerfProfile(vus=2, duration_s=0.6), Thresholds())
    by = {r["name"]: r for r in result["requests"]}
    assert by["Buat"]["errors"] == 0 and by["Tanpa token"]["errors"] == by["Tanpa token"]["count"] > 0


def test_stop_event_ends_early(server):
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    started = time.monotonic()
    result = run_load([PerfRequest(name="ok", method="GET", url=f"{server}/ok")], PerfProfile(vus=3, duration_s=30),
                      Thresholds(), stop_event=stop)
    assert time.monotonic() - started < 5 and result["stopped"] is True


def test_unreachable_host_counts_as_errors():
    result = run_load([PerfRequest(name="mati", method="GET", url="http://127.0.0.1:9/x")],
                      PerfProfile(vus=1, duration_s=0.5, timeout_s=0.5), Thresholds())
    assert result["summary"]["errors"] == result["summary"]["total"] > 0
    assert any(k.startswith("error") for k in result["status_codes"])


def test_parse_curl():
    req = parse_curl("curl -X POST 'https://dev.test/api/wo?x=1' -H 'Authorization: Bearer abc' "
                     "-H \"Content-Type: application/json\" --data-raw '{\"teknisi\":\"T-01\"}'")
    assert req.method == "POST" and req.url == "https://dev.test/api/wo?x=1"
    assert req.headers == {"Authorization": "Bearer abc", "Content-Type": "application/json"}
    assert req.body == '{"teknisi":"T-01"}'
    assert parse_curl("curl https://dev.test/health").method == "GET"
    with pytest.raises(ValueError):
        parse_curl("wget https://x")
