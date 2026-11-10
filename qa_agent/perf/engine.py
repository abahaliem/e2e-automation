"""Mesin uji beban HTTP: virtual user (VU) konkuren dengan asyncio + httpx.

Setiap VU mengulang: pilih request (berbobot) → kirim → catat latency/status → jeda (think time), sampai durasi
habis atau QA menekan Hentikan. VU dinyalakan bertahap selama ramp-up. Ringkasan per detik dikirim lewat
`on_tick` untuk grafik live; hasil akhir berisi statistik per request, kode status, dan penilaian ambang lulus.
"""
from __future__ import annotations

import asyncio
import random
import shlex
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

import httpx

MAX_VUS = 200
MAX_DURATION_S = 1800


@dataclass
class PerfRequest:
    name: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    weight: int = 1
    expect_status: int | None = None  # None = 2xx/3xx dianggap berhasil


@dataclass
class PerfProfile:
    vus: int = 10
    duration_s: float = 60
    ramp_up_s: float = 0
    think_ms: int = 0
    timeout_s: float = 30


@dataclass
class Thresholds:
    p95_ms: float | None = None
    error_rate_pct: float | None = None


def percentile(values: list[float], pct: float) -> float:
    """Persentil nearest-rank (p95 = nilai yang ≥ 95% sampel)."""
    if not values:
        return 0
    ordered = sorted(values)
    k = max(int(-(-pct * len(ordered) // 100)) - 1, 0)  # ceil(pct/100 * n) - 1
    return ordered[min(k, len(ordered) - 1)]


def _stats(latencies: list[float]) -> dict:
    if not latencies:
        return {"p50_ms": 0, "p90_ms": 0, "p95_ms": 0, "p99_ms": 0, "min_ms": 0, "max_ms": 0, "avg_ms": 0}
    return {"p50_ms": round(percentile(latencies, 50), 1), "p90_ms": round(percentile(latencies, 90), 1),
            "p95_ms": round(percentile(latencies, 95), 1), "p99_ms": round(percentile(latencies, 99), 1),
            "min_ms": round(min(latencies), 1), "max_ms": round(max(latencies), 1),
            "avg_ms": round(sum(latencies) / len(latencies), 1)}


def parse_curl(text: str) -> PerfRequest:
    """Satu perintah cURL (mis. disalin dari DevTools/Postman) → PerfRequest."""
    try:
        parts = shlex.split(text.replace("\\\n", " ").replace("^\n", " "))
    except ValueError as e:
        raise ValueError(f"Perintah cURL tidak bisa dibaca: {e}") from e
    if not parts or parts[0].lower() != "curl":
        raise ValueError("Tempel perintah yang diawali 'curl'")
    method, url, headers, body = None, None, {}, None
    i = 1
    while i < len(parts):
        p = parts[i]
        if p in ("-X", "--request") and i + 1 < len(parts):
            method, i = parts[i + 1].upper(), i + 2
        elif p in ("-H", "--header") and i + 1 < len(parts):
            name, _, value = parts[i + 1].partition(":")
            headers[name.strip()] = value.strip()
            i += 2
        elif p in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--json") and i + 1 < len(parts):
            body, i = parts[i + 1], i + 2
            if p == "--json":
                headers.setdefault("Content-Type", "application/json")
        elif p.startswith("http://") or p.startswith("https://"):
            url, i = p, i + 1
        elif p in ("--url",) and i + 1 < len(parts):
            url, i = parts[i + 1], i + 2
        else:
            i += 1  # opsi lain (-s, --compressed, -k, ...) diabaikan
    if not url:
        raise ValueError("URL tidak ditemukan di perintah cURL")
    return PerfRequest(name=url.split("?", 1)[0].rsplit("/", 1)[-1] or url, method=method or ("POST" if body else "GET"),
                       url=url, headers=headers, body=body)


@dataclass
class _Sample:
    t: float  # detik sejak mulai
    req: int
    ms: float
    ok: bool
    status: str


def run_load(requests: list[PerfRequest], profile: PerfProfile, thresholds: Thresholds, *,
             on_tick: Callable[[dict], None] | None = None, stop_event: threading.Event | None = None) -> dict:
    """Jalankan uji beban (memblok sampai selesai). Aman dipanggil dari thread worker."""
    if not requests:
        raise ValueError("Tambahkan minimal satu request")
    vus = max(1, min(int(profile.vus), MAX_VUS))
    duration = max(0.1, min(float(profile.duration_s), MAX_DURATION_S))
    return asyncio.run(_run(requests, PerfProfile(vus, duration, max(profile.ramp_up_s, 0), max(profile.think_ms, 0),
                                                  profile.timeout_s), thresholds, on_tick, stop_event or threading.Event()))


async def _run(requests, profile, thresholds, on_tick, stop_event) -> dict:
    samples: list[_Sample] = []
    weights = [max(r.weight, 1) for r in requests]
    rng = random.Random(7)
    started = time.monotonic()
    active = {"n": 0}
    timeline: list[dict] = []

    def done() -> bool:
        return stop_event.is_set() or time.monotonic() - started >= profile.duration_s

    limits = httpx.Limits(max_connections=profile.vus * 2, max_keepalive_connections=profile.vus)
    async with httpx.AsyncClient(timeout=profile.timeout_s, limits=limits, follow_redirects=False, verify=True) as client:
        started = time.monotonic()  # waktu uji dihitung setelah klien siap (memuat sertifikat bisa ±1 detik)

        async def vu(index: int) -> None:
            delay = profile.ramp_up_s * index / profile.vus if profile.vus > 1 else 0
            while delay > 0 and not done():
                step = min(delay, 0.1)
                await asyncio.sleep(step)
                delay -= step
            if done():
                return
            active["n"] += 1
            try:
                while not done():
                    i = rng.choices(range(len(requests)), weights)[0]
                    r = requests[i]
                    t0 = time.monotonic()
                    try:
                        resp = await client.request(r.method, r.url, headers=r.headers or None,
                                                    content=r.body.encode("utf-8") if r.body else None)
                        code = resp.status_code
                        ok = code == r.expect_status if r.expect_status else code < 400
                        status = str(code)
                    except httpx.HTTPError as e:
                        ok, status = False, f"error: {type(e).__name__}"
                    t1 = time.monotonic()
                    samples.append(_Sample(t=t1 - started, req=i, ms=(t1 - t0) * 1000, ok=ok, status=status))
                    if profile.think_ms:
                        await asyncio.sleep(profile.think_ms / 1000)
            finally:
                active["n"] -= 1

        async def ticker() -> None:
            last = 0
            while not done():
                await asyncio.sleep(min(1.0, max(profile.duration_s / 4, 0.1)))
                now = time.monotonic() - started
                window = [s for s in samples[last:]]
                last = len(samples)
                span = max(now - (timeline[-1]["elapsed_s"] if timeline else 0), 0.001)
                point = {"elapsed_s": round(now, 1), "vus": active["n"], "requests": len(window),
                         "rps": round(len(window) / span, 1), "errors": sum(1 for s in window if not s.ok),
                         "p95_ms": round(percentile([s.ms for s in window], 95), 1), "total": len(samples)}
                timeline.append(point)
                if on_tick:
                    try:
                        on_tick(point)
                    except Exception:
                        pass

        await asyncio.gather(ticker(), *(vu(i) for i in range(profile.vus)))

    elapsed = max(time.monotonic() - started, 0.001)
    by_req: dict[int, list[_Sample]] = defaultdict(list)
    for s in samples:
        by_req[s.req].append(s)
    total, errors = len(samples), sum(1 for s in samples if not s.ok)
    summary = {"total": total, "errors": errors, "error_rate_pct": round(100 * errors / total, 2) if total else 0,
               "rps": round(total / elapsed, 1), "duration_s": round(elapsed, 1), "vus": profile.vus,
               **_stats([s.ms for s in samples])}
    per_request = []
    for i, r in enumerate(requests):
        items = by_req.get(i, [])
        errs = sum(1 for s in items if not s.ok)
        per_request.append({"name": r.name, "method": r.method, "url": r.url, "count": len(items), "errors": errs,
                            "error_rate_pct": round(100 * errs / len(items), 2) if items else 0,
                            "status_codes": dict(Counter(s.status for s in items)), **_stats([s.ms for s in items])})
    checks = []
    if thresholds.p95_ms is not None:
        checks.append({"name": "p95 latency", "target": f"≤ {thresholds.p95_ms:g} ms", "actual": f"{summary['p95_ms']:g} ms",
                       "passed": summary["p95_ms"] <= thresholds.p95_ms})
    if thresholds.error_rate_pct is not None:
        checks.append({"name": "Error rate", "target": f"≤ {thresholds.error_rate_pct:g}%",
                       "actual": f"{summary['error_rate_pct']:g}%",
                       "passed": summary["error_rate_pct"] <= thresholds.error_rate_pct})
    return {"summary": summary, "requests": per_request, "status_codes": dict(Counter(s.status for s in samples)),
            "timeline": timeline, "verdict": {"passed": all(c["passed"] for c in checks), "checks": checks},
            "stopped": stop_event.is_set()}
