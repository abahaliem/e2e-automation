"""RunManager: antrian run dashboard, satu worker thread per run.

Playwright tidak thread-safe, jadi semua panggilan driver (termasuk menyalakan layar live)
terjadi di worker thread run tersebut. Thread server hanya mengubah flag/antrian.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError

from qa_agent.agent.control import InterventionError, RunControl
from qa_agent.config import Config, ConfigError, Credentials
from qa_agent.evidence import RunStore, now_iso, slugify
from qa_agent.llm.base import LLMClient, LLMError
from qa_agent.models import STATUSES, AppMap, RunMeta
from qa_agent.orchestrator.auth import LoginFailed
from qa_agent.orchestrator.deep import PlanError
from qa_agent.report.build import build_reports
from qa_agent.report.excel import ReportLockedError
from qa_agent.runtime import build_runtime, make_explorer, make_planner, make_runner
from qa_agent.server.events import EventHub
from qa_agent.server.secrets import SecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import ProfileRow, RunRow, Store

LLMFactory = Callable[[ProfileRow], LLMClient]
RESUMABLE = ("paused", "interrupted")
COMMANDS = ("pause", "resume", "takeover", "release", "hint", "think_again", "skip", "stop", "end_case",
            "confirm_step", "input")


def friendly_error(e: Exception) -> str:
    """Pesan error yang bisa dibaca QA (tanpa kotak ASCII Playwright), dengan langkah perbaikan bila dikenal."""
    text = str(e)
    if "Executable doesn't exist" in text or "playwright install" in text:
        return ("Browser Chromium untuk testing tidak ditemukan atau sedang diblokir (mis. dipindai antivirus). "
                "Jalankan: .venv/Scripts/python -m playwright install chromium, lalu klik Lanjutkan run.")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip() and not set(ln.strip()) & set("╔╗╚╝║═")), "")
    return f"Error tak terduga: {type(e).__name__}: {first[:300]}"


class RunPaused(Exception):
    """Run tidak bisa dimulai/dilanjutkan sampai pengguna memperbaiki pengaturan."""


@dataclass
class RunRequest:
    app_id: int
    mode: Literal["explore", "deep"]
    module: str | None = None
    prd_text: str | None = None
    profile_id: int | None = None
    account_id: int | None = None
    environment: Literal["dev", "production"] = "dev"
    confirm_each_step: bool = False


@dataclass
class _Active:
    run_id: int
    control: RunControl
    thread: threading.Thread | None = None
    driver: Any = None
    streaming: bool = False
    extras: dict = field(default_factory=dict)


def _provider(value: str) -> str:
    return "anthropic" if value == "anthropic" else "openai_compatible"


class RunManager:
    def __init__(self, store: Store, secrets: SecretStore, hub: EventHub, settings: ServerSettings,
                 llm_factory: LLMFactory | None = None) -> None:
        self.store = store
        self.secrets = secrets
        self.hub = hub
        self.settings = settings
        self.llm_factory = llm_factory
        self._lock = threading.RLock()
        self._active: dict[int, _Active] = {}
        self._queue: list[int] = []
        self._stopping = False
        hub.on_viewers_changed = self._viewers_changed

    # ------------------------------------------------------------------ siklus hidup
    def start(self) -> int:
        """Run yang masih berjalan/menunggu saat server mati ditandai Terhenti."""
        return self.store.mark_unfinished_interrupted()

    def shutdown(self, timeout: float = 15.0) -> None:
        with self._lock:
            self._stopping = True
            self._queue.clear()
            active = list(self._active.values())
        for a in active:
            a.control.stop()
        for a in active:
            if a.thread is not None:
                a.thread.join(timeout)

    # ------------------------------------------------------------------ API publik
    def modules(self, app_id: int) -> list[str]:
        app_map = self._latest_app_map(app_id)
        return app_map.modules() if app_map else []

    def _latest_app_map(self, app_id: int) -> AppMap | None:
        run = self.store.latest_completed_explore(app_id)
        if run is None:
            return None
        return RunStore(Path(run.folder)).read_app_map()

    def submit(self, req: RunRequest) -> RunRow:
        app = self.store.get_app(req.app_id)
        if app is None:
            raise ValueError("Aplikasi tidak ditemukan")
        profile_id = req.profile_id or app.default_profile_id
        profile = self.store.get_profile(profile_id) if profile_id else self.store.get_default_profile()
        if profile is None:
            raise ValueError("Belum ada profil AI. Tambahkan di Pengaturan > Model AI")
        if req.account_id is not None:
            account = self.store.get_account(req.account_id)
            if account is None or account.app_id != app.id:
                raise ValueError("Akun test tidak ditemukan untuk aplikasi ini")
        options: dict[str, Any] = {"confirm_each_step": req.confirm_each_step}
        module = None
        if req.mode == "deep":
            explore = self.store.latest_completed_explore(app.id)
            app_map = RunStore(Path(explore.folder)).read_app_map() if explore else None
            if explore is None or app_map is None:
                raise ValueError("Jalankan Seluruh aplikasi dulu untuk memetakan modul")
            module = app_map.find_module(req.module or "")
            if module is None:
                raise ValueError(f"Modul '{(req.module or '').strip()}' tidak ditemukan. "
                                 f"Modul yang tersedia: {', '.join(app_map.modules())}")
            options["source_run"] = explore.id
            if req.prd_text:
                options["prd_text"] = req.prd_text
        label = module or urlsplit(app.url).netloc or app.name
        folder = RunStore.create(self.settings.runs_dir, req.mode, label).root
        row = self.store.create_run(app_id=app.id, mode=req.mode, module=module, environment=req.environment,
                                    folder=str(folder), profile_id=profile.id, account_id=req.account_id,
                                    model=profile.model, options=options)
        self._publish_status(row)
        self._enqueue(row.id)
        return self.store.get_run(row.id)  # type: ignore[return-value]

    def resume(self, run_id: int) -> RunRow:
        row = self.store.get_run(run_id)
        if row is None:
            raise KeyError(run_id)
        if row.status not in RESUMABLE:
            raise InterventionError("Hanya run yang dijeda atau terhenti yang bisa dilanjutkan")
        row = self.store.update_run(run_id, status="queued", note="", finished_at=None,
                                    options={**row.options, "resume": True})
        self._publish_status(row)
        self._enqueue(run_id)
        return row

    def is_active(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._active

    def control(self, run_id: int) -> RunControl:
        with self._lock:
            active = self._active.get(run_id)
        if active is None:
            raise InterventionError("Run tidak sedang berjalan")
        return active.control

    def command(self, run_id: int, command: str, *, text: str | None = None, status: str | None = None,
                note: str | None = None, event: dict | None = None) -> dict:
        if command not in COMMANDS:
            raise ValueError(f"Perintah tidak dikenal: {command}")
        control = self.control(run_id)
        if command == "hint":
            control.hint(text or "")
        elif command == "end_case":
            control.end_case(status or "", note or "")
        elif command == "input":
            control.queue_input(event or {})
        else:
            getattr(control, command)()
        state = {"type": "control.state", "state": control.state, "command": command}
        if command == "hint":
            state["hint"] = text
        self.hub.publish(run_id, state)
        return {"state": control.state}

    # ------------------------------------------------------------------ antrian
    def _enqueue(self, run_id: int) -> None:
        with self._lock:
            if self._stopping:
                return
            if run_id not in self._queue and run_id not in self._active:
                self._queue.append(run_id)
        self._dispatch()

    def _busy_apps(self) -> set[int]:
        apps = set()
        for a in self._active.values():
            row = self.store.get_run(a.run_id)
            if row is not None:
                apps.add(row.app_id)
        return apps

    def _dispatch(self) -> None:
        with self._lock:
            if self._stopping:
                return
            busy = self._busy_apps()
            for run_id in list(self._queue):
                if len(self._active) >= self.settings.max_parallel:
                    break
                row = self.store.get_run(run_id)
                if row is None:
                    self._queue.remove(run_id)
                    continue
                if row.app_id in busy:
                    continue  # satu aplikasi satu run (berbagi sesi login)
                self._queue.remove(run_id)
                busy.add(row.app_id)
                active = _Active(run_id=run_id,
                                 control=RunControl(confirm_each_step=bool(row.options.get("confirm_each_step"))))
                active.thread = threading.Thread(target=self._worker, args=(active,), name=f"run-{run_id}", daemon=True)
                self._active[run_id] = active
                active.thread.start()

    def _worker(self, active: _Active) -> None:
        try:
            self._execute(active)
        finally:
            with self._lock:
                self._active.pop(active.run_id, None)
            self._dispatch()

    # ------------------------------------------------------------------ status & event
    def _publish_status(self, row: RunRow) -> None:
        event = {"type": "run.status", "status": row.status, "counts": row.counts, "note": row.note}
        self.hub.publish(row.id, event)
        self.hub.publish_global({**event, "run_id": row.id, "app_id": row.app_id, "mode": row.mode,
                                 "module": row.module})

    def _viewers_changed(self, run_id: Any, count: int) -> None:
        pass  # worker membaca viewer_count sendiri di thread-nya (lihat _sync_stream)

    def _sync_stream(self, active: _Active) -> None:
        """Dipanggil HANYA di worker thread: nyalakan/matikan screencast sesuai ada tidaknya penonton."""
        driver = active.driver
        if driver is None:
            return
        want = self.hub.viewer_count(active.run_id) > 0
        if want != active.streaming:
            active.streaming = want
            try:
                driver.set_streaming(want)
            except Exception:
                pass

    # ------------------------------------------------------------------ eksekusi
    def _credentials(self, row: RunRow) -> Credentials:
        if row.account_id is None:
            return Credentials(role="default", username="", password="")
        account = self.store.get_account(row.account_id)
        if account is None:
            raise RunPaused("Akun test sudah dihapus. Pilih akun lain lalu jalankan ulang")
        password = self.secrets.get(f"account:{account.id}")
        if not password:
            raise RunPaused(f"Password akun '{account.role}' belum disimpan. Isi di Aplikasi > Akun test")
        return Credentials(role=account.role, username=account.username, password=password)

    def _config(self, row: RunRow, profile: ProfileRow, role: str) -> Config:
        app = self.store.get_app(row.app_id)
        assert app is not None
        try:
            return Config.model_validate({
                "target": {"url": app.url, "allowed_domains": app.allowed_domains,
                           "login_endpoints": app.login_endpoints},
                "environment": row.environment,
                "accounts": [{"role": role, "username_env": "-", "password_env": "-"}],
                "llm": {"provider": _provider(profile.provider), "base_url": profile.base_url or None,
                        "model": profile.model, "api_key_env": "-", "vision": profile.vision,
                        "timeout_seconds": profile.timeout_seconds},
                "browser": {"headless": True},
            })
        except ValidationError as e:
            raise RunPaused(f"Pengaturan aplikasi tidak valid: {e.errors()[0]['msg']}") from e

    def _llm(self, profile: ProfileRow) -> tuple[LLMClient | None, str | None]:
        if self.llm_factory is not None:
            return self.llm_factory(profile), None
        key = self.secrets.get(f"ai-profile:{profile.id}")
        if not key:
            raise RunPaused(f"API key profil AI '{profile.name}' belum diisi. Isi di Pengaturan > Model AI")
        return None, key

    def _execute(self, active: _Active) -> None:
        run_id = active.run_id
        row = self.store.get_run(run_id)
        assert row is not None
        rs = RunStore(Path(row.folder))
        row = self.store.update_run(run_id, status="running", note="")
        self._publish_status(row)
        resume = bool(row.options.get("resume"))
        meta = rs.read_meta() if (resume and rs.meta_path.exists()) else None
        status, note = "completed", ""
        rt = None

        def on_event(event: dict) -> None:
            self._sync_stream(active)
            self.hub.publish(run_id, event)
            if event.get("type") == "tc.finished":
                cases = rs.read_testcases()
                self.store.upsert_cases(run_id, cases)
                counts = {s: n for s in STATUSES if (n := sum(1 for c in cases if c.status_ai == s))}
                updated = self.store.update_run(run_id, counts=counts)
                self._publish_status(updated)

        try:
            profile = self.store.get_profile(row.profile_id) if row.profile_id else self.store.get_default_profile()
            if profile is None:
                raise RunPaused("Profil AI sudah dihapus. Pilih profil lain")
            creds = self._credentials(row)
            cfg = self._config(row, profile, creds.role)
            llm, api_key = self._llm(profile)
            auth_state = self.settings.auth_dir / f"app-{row.app_id}-{slugify(creds.role)}.json"
            rt = build_runtime(cfg, rs, self.settings.data_dir, environment=row.environment, llm=llm,
                               credentials=creds, api_key=api_key, control=active.control, on_event=on_event,
                               auth_state=auth_state)
            if meta is None:
                meta = RunMeta(mode=row.mode, target=cfg.target.url, environment=row.environment,  # type: ignore[arg-type]
                               model=profile.model, started_at=now_iso(), module=row.module)
            meta.status, meta.finished_at, meta.note = "running", None, ""
            rs.write_meta(meta)
            driver = rt.driver
            driver.set_frame_sink(lambda jpeg, info: self.hub.publish_frame(run_id, jpeg, info))
            active.control.idle = lambda: (self._sync_stream(active), driver.pump(100))
            driver.start()
            active.driver = driver
            self._sync_stream(active)
            if row.mode == "explore":
                make_explorer(rt).run()
            else:
                self._run_deep(rt, rs, row, resume)
            if active.control.state == "stopped":
                status, note = "interrupted", ("Server berhenti" if self._stopping else "Dihentikan oleh QA")
        except RunPaused as e:
            status, note = "paused", str(e)
        except LLMError as e:
            status, note = "paused", f"Endpoint AI bermasalah: {e}"
        except LoginFailed as e:
            status, note = "paused", f"Login gagal: {e}. Periksa akun test di halaman Aplikasi"
        except (PlanError, ConfigError) as e:
            status, note = "paused", str(e)
        except Exception as e:  # laporan parsial tetap ditulis
            status, note = "interrupted", friendly_error(e)
        finally:
            active.driver = None
            if rt is not None:
                try:
                    rt.driver.stop()
                except Exception:
                    pass
            self._finish(run_id, rs, meta, status, note)

    def _run_deep(self, rt, rs: RunStore, row: RunRow, resume: bool) -> None:
        source = self.store.get_run(int(row.options.get("source_run", 0)))
        app_map = RunStore(Path(source.folder)).read_app_map() if source else rs.read_app_map()
        if app_map is None:
            raise RunPaused("Hasil explore sumber tidak ditemukan. Jalankan Seluruh aplikasi lagi")
        module = app_map.find_module(row.module or "") or (row.module or "")
        rs.write_app_map(app_map)
        cases = rs.read_testcases() if resume else []
        if not cases:
            cases = make_planner(rt).plan(app_map, module, row.options.get("prd_text"))
            rs.write_testcases(cases)
        self.store.upsert_cases(row.id, cases)
        self.hub.publish(row.id, {"type": "cases.planned",
                                  "cases": [{"tc_id": c.id, "title": c.title, "status": c.status_ai} for c in cases]})
        needs_auth = not all(s.public for s in app_map.screens_for(module))
        make_runner(rt).execute(cases, needs_auth=needs_auth)

    def _finish(self, run_id: int, rs: RunStore, meta: RunMeta | None, status: str, note: str) -> None:
        if meta is not None:
            meta.status, meta.finished_at, meta.note = status, now_iso(), note  # type: ignore[assignment]
            try:
                rs.write_meta(meta)
                build_reports(rs)
            except ReportLockedError as e:
                note = f"{note} ({e})" if note else str(e)
            except Exception:
                pass
        cases = rs.read_testcases()
        counts = {s: n for s in STATUSES if (n := sum(1 for c in cases if c.effective_status == s))}
        if cases:
            self.store.upsert_cases(run_id, cases)
        row = self.store.update_run(run_id, status=status, finished_at=now_iso(), note=note, counts=counts)
        self._publish_status(row)
        self.hub.publish(run_id, {"type": "run.finished", "status": status, "note": note})
