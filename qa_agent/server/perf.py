"""Uji beban dari dashboard: satu uji berjalan sekaligus (laptop QA), grafik live, hasil & Excel."""
from __future__ import annotations

import io
import json
import threading
from urllib.parse import urlsplit

from qa_agent.perf.engine import PerfProfile, PerfRequest, Thresholds, run_load
from qa_agent.server.secrets import SecretStore
from qa_agent.server.store import Store

SECRET_HEADER_NAMES = ("authorization", "cookie", "x-api-key", "api-key", "x-auth-token", "token", "proxy-authorization")


def perf_secret_key(test_id: int) -> str:
    return f"perf:{test_id}:headers"


def parse_header_lines(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError("secret_headers::Header ditulis 'Nama: nilai' per baris")
        name, value = line.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def is_secret_header(name: str) -> bool:
    return name.lower() in SECRET_HEADER_NAMES or "token" in name.lower() or "secret" in name.lower()


def allowed_hosts(app) -> set[str]:
    hosts = {d.lower() for d in (app.allowed_domains or [])}
    host = urlsplit(app.url).hostname
    if host and not app.url.startswith("android://"):
        hosts.add(host.lower())
    return hosts


class PerfManager:
    def __init__(self, store: Store, secrets: SecretStore) -> None:
        self.store, self.secrets = store, secrets
        self._lock = threading.Lock()
        self._running: dict[int, dict] = {}  # run_id → {"stop": Event, "timeline": [...], "thread": Thread}

    def active_run(self) -> int | None:
        with self._lock:
            return next(iter(self._running), None)

    def live_timeline(self, run_id: int) -> list[dict] | None:
        with self._lock:
            state = self._running.get(run_id)
            return list(state["timeline"]) if state else None

    def start(self, test: dict, *, created_by: str | None = None) -> dict:
        with self._lock:
            if self._running:
                raise RuntimeError("Masih ada uji beban yang sedang berjalan. Tunggu selesai atau hentikan dulu")
            cfg = test["config"]
            run = self.store.create_perf_run(test_id=test["id"], app_id=test["app_id"], name=test["name"], config=cfg,
                                             created_by=created_by)
            state = {"stop": threading.Event(), "timeline": []}
            self._running[run["id"]] = state
        secret = json.loads(self.secrets.get(perf_secret_key(test["id"])) or "{}")
        requests = [PerfRequest(name=r["name"], method=r["method"], url=r["url"], headers={**r.get("headers", {}), **secret},
                                body=r.get("body") or None, weight=int(r.get("weight") or 1),
                                expect_status=r.get("expect_status") or None) for r in cfg["requests"]]
        p, t = cfg["profile"], cfg.get("thresholds", {})
        profile = PerfProfile(vus=int(p["vus"]), duration_s=float(p["duration_s"]), ramp_up_s=float(p.get("ramp_up_s") or 0),
                              think_ms=int(p.get("think_ms") or 0))
        thresholds = Thresholds(p95_ms=t.get("p95_ms"), error_rate_pct=t.get("error_rate_pct"))

        def work() -> None:
            status, result, note = "completed", {}, ""
            try:
                result = run_load(requests, profile, thresholds, on_tick=state["timeline"].append,
                                  stop_event=state["stop"])
                if result.get("stopped"):
                    status, note = "stopped", "Dihentikan oleh QA"
            except Exception as e:  # noqa: BLE001 - hasil gagal tetap dicatat
                status, note = "failed", f"{type(e).__name__}: {e}"
            finally:
                self.store.finish_perf_run(run["id"], status=status, result=result, note=note)
                with self._lock:
                    self._running.pop(run["id"], None)

        thread = threading.Thread(target=work, name=f"perf-{run['id']}", daemon=True)
        state["thread"] = thread
        thread.start()
        return run

    def stop(self, run_id: int) -> bool:
        with self._lock:
            state = self._running.get(run_id)
        if state is None:
            return False
        state["stop"].set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            states = list(self._running.values())
        for s in states:
            s["stop"].set()
        for s in states:
            if s.get("thread"):
                s["thread"].join(10)


def perf_xlsx(run: dict) -> bytes:
    """Laporan uji beban Excel: ringkasan + ambang, per request, timeline per detik."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    result = run.get("result") or {}
    s = result.get("summary", {})
    cfg = run.get("config", {})
    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    rows = [("Uji beban", run["name"]), ("Status", run["status"]), ("Mulai", run["started_at"]),
            ("Selesai", run.get("finished_at") or "-"), ("Virtual user", cfg.get("profile", {}).get("vus")),
            ("Durasi (detik)", s.get("duration_s")), ("Total request", s.get("total")), ("Request/detik", s.get("rps")),
            ("Error", s.get("errors")), ("Error rate (%)", s.get("error_rate_pct")), ("p50 (ms)", s.get("p50_ms")),
            ("p90 (ms)", s.get("p90_ms")), ("p95 (ms)", s.get("p95_ms")), ("p99 (ms)", s.get("p99_ms")),
            ("Maks (ms)", s.get("max_ms")), ("", "")]
    for row in rows:
        ws.append(row)
    verdict = result.get("verdict", {})
    ws.append(["Hasil", "LULUS" if verdict.get("passed") else "GAGAL"])
    for c in verdict.get("checks", []):
        ws.append([c["name"], f"{c['actual']} (target {c['target']})", "Lulus" if c["passed"] else "Gagal"])
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 40
    head = PatternFill("solid", fgColor="2560E8")
    per = wb.create_sheet("Per Request")
    per.append(["Request", "Method", "URL", "Jumlah", "Error", "Error rate (%)", "p50 (ms)", "p90 (ms)", "p95 (ms)",
                "p99 (ms)", "Maks (ms)", "Kode status"])
    for r in result.get("requests", []):
        per.append([r["name"], r["method"], r["url"], r["count"], r["errors"], r["error_rate_pct"], r["p50_ms"],
                    r["p90_ms"], r["p95_ms"], r["p99_ms"], r["max_ms"],
                    ", ".join(f"{k}: {v}" for k, v in r.get("status_codes", {}).items())])
    tl = wb.create_sheet("Timeline")
    tl.append(["Detik ke", "Virtual user aktif", "Request/detik", "Error", "p95 (ms)"])
    for p in result.get("timeline", []):
        tl.append([p["elapsed_s"], p["vus"], p["rps"], p["errors"], p["p95_ms"]])
    for sheet in (per, tl):
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head
        sheet.column_dimensions["A"].width = 24
    per.column_dimensions["C"].width = 48
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
