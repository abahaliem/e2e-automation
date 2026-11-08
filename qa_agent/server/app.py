"""Aplikasi FastAPI dashboard QA Agent (hanya untuk 127.0.0.1)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from qa_agent.agent.control import InterventionError
from qa_agent.server.events import EventHub
from qa_agent.server.runs import LLMFactory, RunManager
from qa_agent.server.secrets import KeyringSecretStore, SecretStore, SecretStoreUnavailable
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store

STATIC_DIR = Path(__file__).parent / "static"

_MESSAGES = {
    "missing": "Wajib diisi",
    "string_too_short": "Wajib diisi",
    "literal_error": "Pilihan tidak valid",
    "int_parsing": "Harus berupa angka",
    "greater_than_equal": "Nilai terlalu kecil",
    "less_than_equal": "Nilai terlalu besar",
    "string_too_long": "Teks terlalu panjang",
}


def _field_errors(errors: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for err in errors:
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        msg = str(err.get("msg", ""))
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        if "::" in msg:  # validator model: "nama_field::pesan"
            field, msg = msg.split("::", 1)
        else:
            field = loc[-1] if loc else "_"
            msg = _MESSAGES.get(err.get("type", ""), msg)
        out.setdefault(field, msg)
    return out


def _validation_response(errors: list[dict]) -> JSONResponse:
    fields = _field_errors(errors)
    return JSONResponse(status_code=422, content={"detail": "Periksa kembali isian form", "field_errors": fields})


def create_app(settings: ServerSettings, *, secrets: SecretStore | None = None,
               llm_factory: LLMFactory | None = None) -> FastAPI:
    """`llm_factory` hanya untuk test (AI palsu); tidak bisa diaktifkan dari CLI."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        store = Store(settings.db_path)
        hub = EventHub()
        manager = RunManager(store, app.state.secrets, hub, settings, llm_factory=llm_factory)
        manager.start()
        app.state.store, app.state.hub, app.state.manager = store, hub, manager
        try:
            yield
        finally:
            manager.shutdown()
            store.close()

    app = FastAPI(title="QA Agent", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.secrets = secrets or KeyringSecretStore()
    app.state.llm_factory = llm_factory

    @app.exception_handler(RequestValidationError)
    async def _req_validation(request: Request, exc: RequestValidationError):
        errors = list(exc.errors())
        if any(err.get("loc", ("",))[0] == "path" for err in errors):
            return JSONResponse(status_code=404, content={"detail": "Data tidak ditemukan"})
        return _validation_response(errors)

    @app.exception_handler(ValidationError)
    async def _validation(request: Request, exc: ValidationError):
        return _validation_response(list(exc.errors()))

    @app.exception_handler(InterventionError)
    async def _intervention(request: Request, exc: InterventionError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        status = 409 if "riwayat run" in str(exc) else 422
        return JSONResponse(status_code=status, content={"detail": str(exc), "field_errors": {}})

    @app.exception_handler(SecretStoreUnavailable)
    async def _secrets_unavailable(request: Request, exc: SecretStoreUnavailable):
        return JSONResponse(status_code=503, content={
            "detail": "Windows Credential Manager tidak bisa diakses, jadi API key dan password tidak bisa disimpan. "
                      f"({exc})"})

    from qa_agent.server import ws
    from qa_agent.server.api import apps, profiles, results, runs, stats

    for module in (apps, profiles, runs, results, stats, ws):
        app.include_router(module.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"], include_in_schema=False)
    async def _api_not_found(rest: str):
        return JSONResponse(status_code=404, content={"detail": "Endpoint tidak ditemukan"})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        root = STATIC_DIR.resolve()
        index = root / "index.html"
        if full_path:
            try:
                target = (root / full_path).resolve()
                target.relative_to(root)
                if target.is_file():
                    return FileResponse(target)
            except (ValueError, OSError):
                pass
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(status_code=404, content={
            "detail": "Frontend belum di-build. Jalankan: npm --prefix web install && npm --prefix web run build"})

    return app
