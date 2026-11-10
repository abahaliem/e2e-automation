"""API testing dari dashboard: jalankan suite di thread, laporan Excel memakai format laporan (termasuk template kantor)."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from qa_agent.apitest.engine import ApiCase, Assertion, run_suite
from qa_agent.models import QaTestCase, RunMeta
from qa_agent.server.secrets import SecretStore
from qa_agent.server.store import Store

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def api_secret_key(suite_id: int) -> str:
    return f"api:{suite_id}:headers"


def to_cases(raw: list[dict]) -> list[ApiCase]:
    return [ApiCase(name=c["name"], method=c["method"].upper(), url=c["url"], headers=c.get("headers") or {},
                    body=c.get("body") or "", capture=c.get("capture") or {},
                    assertions=[Assertion(kind=a["kind"], op=a.get("op") or "eq", expected=str(a.get("expected") or ""),
                                          path=a.get("path") or "") for a in c.get("assertions") or []])
            for c in raw]


class ApiRunManager:
    def __init__(self, store: Store, secrets: SecretStore) -> None:
        self.store, self.secrets = store, secrets
        self._lock = threading.Lock()
        self._running: dict[int, threading.Event] = {}
        self._progress: dict[int, list[dict]] = {}

    def progress(self, run_id: int) -> list[dict] | None:
        """Hasil test case yang sudah selesai selama run masih berjalan (untuk tampilan live)."""
        with self._lock:
            items = self._progress.get(run_id)
            return list(items) if items is not None else None

    def start(self, suite: dict, *, created_by: str | None = None) -> dict:
        cfg = suite["config"]
        run = self.store.create_api_run(suite_id=suite["id"], app_id=suite["app_id"], name=suite["name"], config=cfg,
                                        created_by=created_by)
        stop = threading.Event()
        with self._lock:
            self._running[run["id"]] = stop
            self._progress[run["id"]] = []
        secret_headers = json.loads(self.secrets.get(api_secret_key(suite["id"])) or "{}")
        variables = {**(cfg.get("variables") or {}), "base_url": (cfg.get("base_url") or "").rstrip("/")}

        def on_case(entry: dict) -> None:
            with self._lock:
                self._progress.setdefault(run["id"], []).append(entry)

        def work() -> None:
            status, result, note = "completed", {}, ""
            try:
                result = run_suite(to_cases(cfg["cases"]), variables=variables, secret_headers=secret_headers, stop=stop,
                                   on_case=on_case)
                if result.get("stopped"):
                    status, note = "stopped", "Dihentikan oleh QA"
            except Exception as e:  # noqa: BLE001
                status, note = "failed", f"{type(e).__name__}: {e}"
            finally:
                self.store.finish_api_run(run["id"], status=status, result=result, note=note)
                with self._lock:
                    self._running.pop(run["id"], None)
                    self._progress.pop(run["id"], None)

        threading.Thread(target=work, name=f"api-{run['id']}", daemon=True).start()
        return run

    def stop(self, run_id: int) -> bool:
        with self._lock:
            event = self._running.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            for event in self._running.values():
                event.set()


def run_as_test_cases(run: dict) -> list[QaTestCase]:
    """Hasil API testing → test case standar (dokumen Excel sama dengan pengujian UI / template kantor)."""
    cfg_cases = {c["name"]: c for c in run["config"].get("cases", [])}
    out = []
    for n, r in enumerate((run.get("result") or {}).get("cases", []), 1):
        cfg = cfg_cases.get(r["name"], {})
        req = r.get("request", {})
        steps = [f"{req.get('method', '')} {req.get('url', '')}"]
        if req.get("body"):
            steps.append(f"Body: {req['body']}")
        for name, path in (cfg.get("capture") or {}).items():
            steps.append(f"Simpan {path} ke {{{{{name}}}}}")
        expected = "; ".join(a["description"] for a in r.get("assertions", [])) or "Status 2xx"
        if r.get("error") and "status" not in r:
            actual, status = f"Request gagal: {r['error']}", "Blocked"
        else:
            failed = [f"{a['description']} → aktual {a['actual']}" for a in r.get("assertions", []) if not a["passed"]]
            actual = (f"HTTP {r.get('status')} dalam {r.get('ms')} ms. "
                      + ("Semua pengecekan sesuai." if not failed else "Tidak sesuai: " + "; ".join(failed)))
            if r.get("error"):
                actual += f" {r['error']}"
            status = "Pass" if r.get("passed") else "Fail"
        out.append(QaTestCase(id=f"API-{n:03d}", module=run["name"], page=req.get("method", ""), title=r["name"],
                              type="positif", steps=steps, expected=expected, actual=actual, status_ai=status,
                              severity="Major" if status == "Fail" else None))
    return out


def api_run_xlsx(run: dict, path: Path, *, template: Path | None, fields: dict, context: dict, sheet: str | None) -> Path:
    from qa_agent.report.excel import write_report_xlsx

    cfg = run["config"]
    meta = RunMeta(mode="deep", target=cfg.get("base_url") or "-", environment=cfg.get("environment", "dev"),
                   model="API testing", started_at=run["started_at"],
                   finished_at=run.get("finished_at") or datetime.now().isoformat(timespec="seconds"),
                   status="completed" if run["status"] == "completed" else "interrupted", module=run["name"])
    write_report_xlsx(path, meta, run_as_test_cases(run), [], None, template=template, fields=fields,
                      context={**context, "Peran": context.get("Peran", "API")}, sheet=sheet)
    return path
