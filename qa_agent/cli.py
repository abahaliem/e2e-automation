from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, NoReturn, Optional
from urllib.parse import urlsplit

import typer

from qa_agent.config import Config, ConfigError, load_config
from qa_agent.evidence import RunStore, now_iso
from qa_agent.imaging import solid_png
from qa_agent.llm.base import LLMError, Message
from qa_agent.llm.factory import build_llm
from qa_agent.models import STATUSES, AppMap, QaTestCase, RunMeta
from qa_agent.orchestrator.auth import LoginFailed
from qa_agent.orchestrator.deep import PlanError
from qa_agent.report.build import build_reports, import_review
from qa_agent.report.excel import ReportLockedError, import_cases_xlsx, write_cases_xlsx
from qa_agent.runtime import Runtime, build_runtime, make_explorer, make_planner, make_runner
from qa_agent.templates import CONFIG_TEMPLATE, ENV_TEMPLATE

app = typer.Typer(help="QA Agent - AI QA automation untuk aplikasi web.", no_args_is_help=True, add_completion=False)
CONFIG_HELP = "File konfigurasi"


def _fail(message: str) -> NoReturn:
    typer.echo(f"[GAGAL] {message}", err=True)
    raise typer.Exit(1)


def _load(config: Path) -> Config:
    try:
        return load_config(config)
    except ConfigError as e:
        _fail(str(e))


def _environment(option: str | None, cfg: Config) -> str:
    env = option or cfg.environment
    if env not in ("dev", "production"):
        _fail("--env harus 'dev' atau 'production'")
    return env


def _project_dir(config: Path) -> Path:
    return config.resolve().parent


def _runtime(cfg: Config, store: RunStore, config: Path, environment: str) -> Runtime:
    try:
        return build_runtime(cfg, store, _project_dir(config), environment=environment)
    except ConfigError as e:
        _fail(str(e))


def _write_reports(store: RunStore) -> None:
    try:
        xlsx, html = build_reports(store)
    except ReportLockedError as e:
        typer.echo(f"[GAGAL] {e}", err=True)
        return
    typer.echo(f"Laporan Excel : {xlsx}")
    typer.echo(f"Laporan HTML  : {html}")


def _finish(store: RunStore, meta: RunMeta, status: str, note: str = "") -> None:
    meta.status = status  # type: ignore[assignment]
    meta.finished_at = now_iso()
    meta.note = note
    store.write_meta(meta)
    _write_reports(store)


def _run_guarded(rt: Runtime, meta: RunMeta, body: Callable[[], object]) -> str:
    rt.stop.install()
    status, note = "completed", ""
    try:
        rt.driver.start()
        body()
        if rt.stop():
            status, note = "interrupted", "Dihentikan dengan Ctrl+C"
    except LLMError as e:
        status, note = "paused", f"Endpoint AI bermasalah: {e}"
    except LoginFailed as e:
        status, note = "paused", f"Login gagal: {e}"
    except KeyboardInterrupt:
        status, note = "interrupted", "Dihentikan paksa"
    except Exception as e:  # jangan sampai laporan tidak ditulis
        status, note = "interrupted", f"Error tak terduga: {type(e).__name__}: {e}"
    finally:
        try:
            rt.driver.stop()
        except Exception:
            pass
        _finish(rt.store, meta, status, note)
    typer.echo(f"Status run: {status}" + (f" - {note}" if note else ""))
    return status


def _check_browser() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True, ""
    except Exception as e:
        return False, f"jalankan: python -m playwright install chromium ({type(e).__name__})"


def _check_target(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return True, f"{url} (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"{url} (HTTP {e.code})"
    except Exception as e:
        return False, f"{url}: {e}"


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Timpa file yang sudah ada")) -> None:
    """Buat qa-agent.yaml dan .env.example di folder ini."""
    for name, content in (("qa-agent.yaml", CONFIG_TEMPLATE), (".env.example", ENV_TEMPLATE)):
        path = Path(name)
        if path.exists() and not force:
            typer.echo(f"[LEWATI] {name} sudah ada (pakai --force untuk menimpa)")
            continue
        path.write_text(content, encoding="utf-8")
        typer.echo(f"[OK] {name} dibuat")
    typer.echo("Berikutnya: salin .env.example menjadi .env, isi nilainya, lalu jalankan 'qa-agent check'.")


@app.command()
def check(config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP)) -> None:
    """Cek config, kredensial, endpoint AI (teks & gambar), browser, dan target."""
    ok = True

    def line(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        typer.echo(f"[{'OK' if passed else 'GAGAL'}] {name}" + (f" - {detail}" if detail else ""))

    try:
        cfg = load_config(config)
    except ConfigError as e:
        line("Config", False, str(e))
        raise typer.Exit(1)
    line("Config", True, str(config))

    secrets_ok = True
    for label, getter in (("Kredensial akun", cfg.credentials), ("API key AI", cfg.api_key)):
        try:
            getter()
            line(label, True)
        except ConfigError as e:
            line(label, False, str(e))
            secrets_ok = False

    if secrets_ok:
        llm = build_llm(cfg)
        try:
            reply = llm.chat("Jawab sangat singkat.", [Message(role="user", text="Balas dengan satu kata: OK")])
            line("Endpoint AI (teks)", bool(reply.strip()), f"{cfg.llm.model}: {reply.strip()[:40]}")
        except LLMError as e:
            line("Endpoint AI (teks)", False, str(e))
        if cfg.llm.vision:
            try:
                reply = llm.chat("Jawab dengan satu kata.", [Message(
                    role="user", text="Apa warna gambar ini? Jawab: merah, hijau, atau biru.",
                    images=[solid_png((220, 20, 20), (64, 64))])])
                line("Endpoint AI (gambar)", any(w in reply.lower() for w in ("merah", "red")), reply.strip()[:40] or "(kosong)")
            except LLMError as e:
                line("Endpoint AI (gambar)", False, str(e))

    line("Browser Chromium", *_check_browser())
    line("Target", *_check_target(cfg.target.url))
    if not ok:
        raise typer.Exit(1)


@app.command()
def explore(
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
    env: Optional[str] = typer.Option(None, "--env", help="dev | production"),
) -> None:
    """Petakan seluruh aplikasi (hanya navigasi) menjadi inventaris fitur."""
    cfg = _load(config)
    environment = _environment(env, cfg)
    store = RunStore.create(_project_dir(config) / "runs", "explore", urlsplit(cfg.target.url).netloc)
    rt = _runtime(cfg, store, config, environment)
    meta = RunMeta(mode="explore", target=cfg.target.url, environment=environment, model=cfg.llm.model, started_at=now_iso())
    store.write_meta(meta)
    typer.echo(f"Folder run: {store.root}")
    status = _run_guarded(rt, meta, make_explorer(rt).run)
    app_map = store.read_app_map()
    if app_map:
        typer.echo(f"Ditemukan {len(app_map.screens)} layar dalam {len(app_map.modules())} modul: {', '.join(app_map.modules())}")
    if status != "completed":
        raise typer.Exit(2)


def _read_prd(prd: Path | None) -> str | None:
    if prd is None:
        return None
    if prd.suffix.lower() not in (".md", ".txt"):
        _fail("PRD harus berupa file .md atau .txt (salin isi PDF/Word ke file teks dulu)")
    if not prd.exists():
        _fail(f"File PRD {prd} tidak ditemukan")
    return prd.read_text(encoding="utf-8")


def _execute(rt: Runtime, meta: RunMeta, app_map: AppMap, cases: list[QaTestCase]) -> None:
    needs_auth = not all(s.public for s in app_map.screens_for(meta.module or ""))
    typer.echo(f"Menjalankan {sum(1 for c in cases if c.status_ai is None)} test case...")
    meta.status = "running"
    rt.store.write_meta(meta)
    status = _run_guarded(rt, meta, lambda: make_runner(rt).execute(cases, needs_auth=needs_auth))
    counts = {s: sum(1 for c in cases if c.status_ai == s) for s in STATUSES}
    typer.echo("Hasil: " + ", ".join(f"{s} {n}" for s, n in counts.items() if n))
    if status == "paused":
        typer.echo(f'Lanjutkan dengan: qa-agent run --run "{rt.store.root}" --resume')
    if status != "completed":
        raise typer.Exit(2)


@app.command()
def deep(
    from_run: Path = typer.Option(..., "--from", help="Folder run hasil explore"),
    module: str = typer.Option(..., "--module", help="Nama modul dari hasil explore"),
    prd: Optional[Path] = typer.Option(None, "--prd", help="File PRD .md/.txt (opsional)"),
    review: bool = typer.Option(False, "--review", help="Berhenti setelah test case disusun untuk direview"),
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
    env: Optional[str] = typer.Option(None, "--env", help="dev | production"),
) -> None:
    """Susun test case untuk satu modul lalu jalankan."""
    cfg = _load(config)
    environment = _environment(env, cfg)
    if not (from_run / "app_map.json").exists():
        _fail(f"{from_run} bukan folder run explore (app_map.json tidak ada)")
    app_map = RunStore(from_run).read_app_map()
    assert app_map is not None
    canonical = app_map.find_module(module)
    if canonical is None:
        _fail(f"Modul '{module.strip()}' tidak ditemukan. Modul yang tersedia: {', '.join(app_map.modules())}")
    prd_text = _read_prd(prd)

    store = RunStore.create(_project_dir(config) / "runs", "deep", canonical)
    store.write_app_map(app_map)
    rt = _runtime(cfg, store, config, environment)
    meta = RunMeta(mode="deep", target=cfg.target.url, environment=environment, model=cfg.llm.model,
                   started_at=now_iso(), module=canonical, source_run=str(from_run))
    store.write_meta(meta)
    typer.echo(f"Folder run: {store.root}")
    typer.echo(f"Menyusun test case untuk modul '{canonical}'...")
    try:
        cases = make_planner(rt).plan(app_map, canonical, prd_text)
    except (PlanError, LLMError) as e:
        _finish(store, meta, "paused", str(e))
        _fail(str(e))
    store.write_testcases(cases)
    typer.echo(f"{len(cases)} test case disusun.")

    if review:
        try:
            write_cases_xlsx(store.cases_xlsx, cases)
        except ReportLockedError as e:
            _fail(str(e))
        _finish(store, meta, "paused", "Menunggu review test case")
        typer.echo(f"Review & edit test case di: {store.cases_xlsx}")
        typer.echo(f'Lalu jalankan: qa-agent run --run "{store.root}"')
        return
    _execute(rt, meta, app_map, cases)


@app.command("run")
def run_command(
    run_dir: Path = typer.Option(..., "--run", help="Folder run mode deep"),
    resume: bool = typer.Option(False, "--resume", help="Lanjutkan test case yang belum selesai"),
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
) -> None:
    """Jalankan test case hasil review, atau lanjutkan run yang terhenti."""
    cfg = _load(config)
    if not (run_dir / "run.json").exists():
        _fail(f"{run_dir} bukan folder run (run.json tidak ada)")
    store = RunStore(run_dir)
    meta = store.read_meta()
    if meta.mode != "deep":
        _fail("Hanya run mode deep yang bisa dijalankan atau dilanjutkan")
    app_map = store.read_app_map() or AppMap(target=meta.target)

    if resume:
        cases = store.read_testcases()
    elif store.cases_xlsx.exists():
        try:
            cases = import_cases_xlsx(store.cases_xlsx)
        except ValueError as e:
            _fail(f"{store.cases_xlsx.name}: {e}")
    else:
        cases = store.read_testcases()
    if not resume:
        for c in cases:
            c.status_ai, c.actual, c.ai_note, c.severity = None, "", "", None
    if not cases:
        _fail("Tidak ada test case untuk dijalankan")
    store.write_testcases(cases)
    rt = _runtime(cfg, store, config, meta.environment)
    _execute(rt, meta, app_map, cases)


@app.command()
def report(run_dir: Path = typer.Option(..., "--run", help="Folder run")) -> None:
    """Buat ulang laporan memakai Status Final dan Catatan Reviewer dari report.xlsx."""
    if not (run_dir / "run.json").exists():
        _fail(f"{run_dir} bukan folder run (run.json tidak ada)")
    store = RunStore(run_dir)
    try:
        n = import_review(store)
        xlsx, html = build_reports(store)
    except ValueError as e:
        _fail(f"report.xlsx: {e}")
    except ReportLockedError as e:
        _fail(str(e))
    typer.echo(f"{n} baris review diimpor.")
    typer.echo(f"Laporan Excel : {xlsx}")
    typer.echo(f"Laporan HTML  : {html}")
