"""Uji beban (Performance): skenario per aplikasi, jalankan, pantau live, hentikan, unduh Excel."""
from __future__ import annotations

import json
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from qa_agent.perf.engine import MAX_DURATION_S, MAX_VUS, parse_curl
from qa_agent.server.api import deps
from qa_agent.server.perf import allowed_hosts, is_secret_header, parse_header_lines, perf_secret_key, perf_xlsx

router = APIRouter(prefix="/api", tags=["performance"])


class PerfRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str = Field(max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="", max_length=100_000)
    weight: int = Field(default=1, ge=1, le=100)
    expect_status: int | None = Field(default=None, ge=100, le=599)


class ProfileIn(BaseModel):
    vus: int = Field(default=10, ge=1, le=MAX_VUS)
    duration_s: float = Field(default=60, gt=0, le=MAX_DURATION_S)
    ramp_up_s: float = Field(default=0, ge=0, le=MAX_DURATION_S)
    think_ms: int = Field(default=0, ge=0, le=60_000)


class ThresholdsIn(BaseModel):
    p95_ms: float | None = Field(default=None, gt=0)
    error_rate_pct: float | None = Field(default=None, ge=0, le=100)


class PerfTestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    requests: list[PerfRequestIn] = Field(min_length=1, max_length=50)
    profile: ProfileIn = Field(default_factory=ProfileIn)
    thresholds: ThresholdsIn = Field(default_factory=ThresholdsIn)
    environment: Literal["dev", "production"] = "dev"
    approved_hosts: list[str] = Field(default_factory=list)  # host di luar domain aplikasi yang dikonfirmasi QA
    secret_headers: str | None = Field(default=None, max_length=8000)  # None = tidak diubah


class RunIn(BaseModel):
    confirm_production: bool = False


def _app_or_404(request: Request, app_id: int):
    app = deps.store(request).get_app(app_id)
    if app is None:
        raise deps.not_found("Aplikasi")
    return app


def _test_or_404(request: Request, test_id: int) -> dict:
    test = deps.store(request).get_perf_test(test_id)
    if test is None:
        raise deps.not_found("Uji beban")
    return test


def _config(request: Request, app, body: PerfTestIn) -> dict:
    allowed = allowed_hosts(app)
    approved = {h.strip().lower() for h in body.approved_hosts if h.strip()}
    for r in body.requests:
        if not r.url.startswith(("http://", "https://")):
            raise ValueError(f"requests::URL '{r.name}' harus diawali http:// atau https://")
        host = (urlsplit(r.url).hostname or "").lower()
        if host not in allowed and host not in approved:
            raise ValueError(f"Host {host} bukan domain aplikasi ini. Konfirmasi bahwa Anda berwenang menguji beban "
                             f"{host}, atau tambahkan ke domain aplikasi")
    if body.profile.ramp_up_s > body.profile.duration_s:
        raise ValueError("profile::Ramp-up tidak boleh lebih lama dari durasi")
    return {"requests": [r.model_dump() for r in body.requests], "profile": body.profile.model_dump(),
            "thresholds": body.thresholds.model_dump(), "environment": body.environment,
            "approved_hosts": sorted(approved)}


def _out(request: Request, test: dict) -> dict:
    return {**test, "has_secret_headers": bool(deps.secrets(request).get(perf_secret_key(test["id"])))}


def _save_secret(request: Request, test_id: int, text: str | None) -> None:
    if text is None:
        return
    headers = parse_header_lines(text)
    if headers:
        deps.secrets(request).set(perf_secret_key(test_id), json.dumps(headers))
    else:
        deps.secrets(request).delete(perf_secret_key(test_id))


@router.get("/apps/{app_id}/perf-tests")
def list_tests(app_id: int, request: Request) -> list[dict]:
    _app_or_404(request, app_id)
    return [_out(request, t) for t in deps.store(request).list_perf_tests(app_id)]


@router.post("/apps/{app_id}/perf-tests", status_code=201)
def create_test(app_id: int, body: PerfTestIn, request: Request) -> dict:
    app = _app_or_404(request, app_id)
    parse_header_lines(body.secret_headers or "")  # validasi sebelum menyimpan
    test = deps.store(request).create_perf_test(app_id=app_id, name=body.name, config=_config(request, app, body))
    _save_secret(request, test["id"], body.secret_headers)
    return _out(request, test)


@router.patch("/perf-tests/{test_id}")
def update_test(test_id: int, body: PerfTestIn, request: Request) -> dict:
    test = _test_or_404(request, test_id)
    app = _app_or_404(request, test["app_id"])
    parse_header_lines(body.secret_headers or "")
    updated = deps.store(request).update_perf_test(test_id, name=body.name, config=_config(request, app, body))
    _save_secret(request, test_id, body.secret_headers)
    return _out(request, updated)


@router.delete("/perf-tests/{test_id}", status_code=204)
def delete_test(test_id: int, request: Request) -> Response:
    _test_or_404(request, test_id)
    if any(r["test_id"] == test_id for r in deps.store(request).list_perf_runs(test_id=test_id) if r["status"] == "running"):
        raise HTTPException(status_code=409, detail="Uji ini sedang berjalan. Hentikan dulu")
    deps.store(request).delete_perf_test(test_id)
    deps.secrets(request).delete(perf_secret_key(test_id))
    return Response(status_code=204)


class CurlIn(BaseModel):
    text: str = Field(max_length=100_000)


@router.post("/perf-tests/import-curl")
def import_curl(body: CurlIn) -> dict:
    """cURL (dari DevTools / Postman) → request; header rahasia (Authorization, Cookie, token) dipisah."""
    req = parse_curl(body.text)
    plain = {k: v for k, v in req.headers.items() if not is_secret_header(k)}
    secret = "\n".join(f"{k}: {v}" for k, v in req.headers.items() if is_secret_header(k))
    return {"request": {"name": req.name, "method": req.method, "url": req.url, "headers": plain, "body": req.body or "",
                        "weight": 1, "expect_status": None},
            "secret_headers": secret}


@router.post("/perf-tests/{test_id}/run")
def run_test(test_id: int, body: RunIn, request: Request) -> dict:
    test = _test_or_404(request, test_id)
    if test["config"].get("environment") == "production" and not body.confirm_production:
        raise HTTPException(status_code=409, detail="Uji beban ke Production bisa mengganggu pengguna nyata. "
                                                    "Konfirmasi dulu untuk menjalankan")
    user = getattr(request.state, "user", None)
    try:
        run = request.app.state.perf.start(test, created_by=user.username if user else None)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return run


@router.get("/perf-tests/{test_id}/runs")
def list_runs(test_id: int, request: Request) -> list[dict]:
    _test_or_404(request, test_id)
    return [_run_brief(r) for r in deps.store(request).list_perf_runs(test_id=test_id)]


def _run_brief(run: dict) -> dict:
    result = run.get("result") or {}
    return {k: v for k, v in run.items() if k != "result"} | {
        "summary": result.get("summary"), "passed": (result.get("verdict") or {}).get("passed")}


@router.get("/perf-runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict:
    run = deps.store(request).get_perf_run(run_id)
    if run is None:
        raise deps.not_found("Uji beban")
    live = request.app.state.perf.live_timeline(run_id)
    if live is not None:  # masih berjalan: grafik dari data per detik di memori
        run["result"] = {"timeline": live}
    return run


@router.post("/perf-runs/{run_id}/stop")
def stop_run(run_id: int, request: Request) -> dict:
    if deps.store(request).get_perf_run(run_id) is None:
        raise deps.not_found("Uji beban")
    return {"stopping": request.app.state.perf.stop(run_id)}


@router.delete("/perf-runs/{run_id}", status_code=204)
def delete_run(run_id: int, request: Request) -> Response:
    run = deps.store(request).get_perf_run(run_id)
    if run is None:
        raise deps.not_found("Uji beban")
    if run["status"] == "running":
        raise HTTPException(status_code=409, detail="Uji ini sedang berjalan. Hentikan dulu")
    deps.store(request).delete_perf_run(run_id)
    return Response(status_code=204)


@router.get("/perf-runs/{run_id}/xlsx")
def download_xlsx(run_id: int, request: Request) -> Response:
    run = deps.store(request).get_perf_run(run_id)
    if run is None:
        raise deps.not_found("Uji beban")
    name = f"uji-beban-run{run_id}.xlsx"
    return Response(perf_xlsx(run), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
