"""API testing: suite per aplikasi, impor Postman/OpenAPI/cURL, susun dengan AI, jalankan, hasil & Excel."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.apitest.importers import from_openapi, from_postman, openapi_base_url, openapi_summary
from qa_agent.llm.base import LLMError, Message
from qa_agent.perf.engine import parse_curl
from qa_agent.server.api import deps
from qa_agent.server.apitesting import WRITE_METHODS, api_run_xlsx, api_secret_key
from qa_agent.server.perf import allowed_hosts, is_secret_header, parse_header_lines

router = APIRouter(prefix="/api", tags=["api-testing"])


class AssertionIn(BaseModel):
    kind: Literal["status", "json", "time", "body", "header"]
    op: Literal["eq", "ne", "contains", "exists", "not_exists", "lt", "gt", "type"] = "eq"
    expected: str = Field(default="", max_length=2000)
    path: str = Field(default="", max_length=300)


class CaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str = Field(min_length=1, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="", max_length=100_000)
    assertions: list[AssertionIn] = Field(default_factory=list, max_length=30)
    capture: dict[str, str] = Field(default_factory=dict)


class SuiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(default="", max_length=500)
    environment: Literal["dev", "production"] = "dev"
    approved_hosts: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    cases: list[CaseIn] = Field(min_length=1, max_length=300)
    secret_headers: str | None = Field(default=None, max_length=8000)  # None = tidak diubah


def _app_or_404(request: Request, app_id: int):
    app = deps.store(request).get_app(app_id)
    if app is None:
        raise deps.not_found("Aplikasi")
    return app


def _suite_or_404(request: Request, suite_id: int) -> dict:
    suite = deps.store(request).get_api_suite(suite_id)
    if suite is None:
        raise deps.not_found("Suite API")
    return suite


def _config(app, body: SuiteIn) -> dict:
    base = body.base_url.strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        raise ValueError("base_url::Base URL harus diawali http:// atau https://")
    allowed = allowed_hosts(app)
    approved = {h.strip().lower() for h in body.approved_hosts if h.strip()}
    urls = [base] + [c.url.replace("{{base_url}}", base) for c in body.cases]
    for url in urls:
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlsplit(url).hostname or "").lower()
        if host and host not in allowed and host not in approved:
            raise ValueError(f"Host {host} bukan domain aplikasi ini. Konfirmasi bahwa Anda berwenang menguji API "
                             f"{host}, atau tambahkan ke domain aplikasi")
    return {"base_url": base, "environment": body.environment, "approved_hosts": sorted(approved),
            "variables": body.variables, "cases": [c.model_dump() for c in body.cases]}


def _out(request: Request, suite: dict) -> dict:
    return {**suite, "has_secret_headers": bool(deps.secrets(request).get(api_secret_key(suite["id"])))}


def _save_secret(request: Request, suite_id: int, text: str | None) -> None:
    if text is None:
        return
    headers = parse_header_lines(text)
    key = api_secret_key(suite_id)
    deps.secrets(request).set(key, json.dumps(headers)) if headers else deps.secrets(request).delete(key)


@router.get("/apps/{app_id}/api-suites")
def list_suites(app_id: int, request: Request) -> list[dict]:
    _app_or_404(request, app_id)
    return [_out(request, s) for s in deps.store(request).list_api_suites(app_id)]


@router.post("/apps/{app_id}/api-suites", status_code=201)
def create_suite(app_id: int, body: SuiteIn, request: Request) -> dict:
    app = _app_or_404(request, app_id)
    parse_header_lines(body.secret_headers or "")
    suite = deps.store(request).create_api_suite(app_id=app_id, name=body.name, config=_config(app, body))
    _save_secret(request, suite["id"], body.secret_headers)
    return _out(request, suite)


@router.patch("/api-suites/{suite_id}")
def update_suite(suite_id: int, body: SuiteIn, request: Request) -> dict:
    suite = _suite_or_404(request, suite_id)
    app = _app_or_404(request, suite["app_id"])
    parse_header_lines(body.secret_headers or "")
    updated = deps.store(request).update_api_suite(suite_id, name=body.name, config=_config(app, body))
    _save_secret(request, suite_id, body.secret_headers)
    return _out(request, updated)


@router.delete("/api-suites/{suite_id}", status_code=204)
def delete_suite(suite_id: int, request: Request) -> Response:
    _suite_or_404(request, suite_id)
    deps.store(request).delete_api_suite(suite_id)
    deps.secrets(request).delete(api_secret_key(suite_id))
    return Response(status_code=204)


class ImportIn(BaseModel):
    kind: Literal["postman", "openapi", "curl"]
    text: str = Field(max_length=5_000_000)


def _case_out(c) -> dict:
    return {"name": c.name, "method": c.method, "url": c.url, "headers": c.headers, "body": c.body,
            "assertions": [{"kind": a.kind, "op": a.op, "expected": a.expected, "path": a.path} for a in c.assertions],
            "capture": c.capture}


@router.post("/api-suites/import")
def import_cases(body: ImportIn) -> dict:
    """Postman collection / OpenAPI / cURL → test case (belum disimpan; QA review dulu di editor)."""
    if body.kind == "postman":
        return {"cases": [_case_out(c) for c in from_postman(body.text)], "base_url": "", "secret_headers": ""}
    if body.kind == "openapi":
        return {"cases": [_case_out(c) for c in from_openapi(body.text)], "base_url": openapi_base_url(body.text),
                "secret_headers": ""}
    req = parse_curl(body.text)
    plain = {k: v for k, v in req.headers.items() if not is_secret_header(k)}
    secret = "\n".join(f"{k}: {v}" for k, v in req.headers.items() if is_secret_header(k))
    case = {"name": req.name, "method": req.method, "url": req.url, "headers": plain, "body": req.body or "",
            "assertions": [{"kind": "status", "op": "eq", "expected": "2xx", "path": ""}], "capture": {}}
    return {"cases": [case], "base_url": "", "secret_headers": secret}


API_PLAN_SYSTEM = """MODE: API_PLAN
Kamu QA engineer senior untuk pengujian API. Susun test case API dari daftar endpoint berikut.
Jawab HANYA satu objek JSON: {"cases": [ ... ]}
Format tiap test case:
{"name": "skenario singkat (Bahasa Indonesia)", "method": "GET|POST|PUT|PATCH|DELETE", "path": "/path/{{variabel}}",
 "headers": {}, "body": "JSON body sebagai teks atau kosong",
 "assertions": [{"kind": "status|json|time|body|header", "op": "eq|ne|contains|exists|not_exists|lt|gt|type", "expected": "...", "path": "json.path untuk kind json"}],
 "capture": {"nama_variabel": "json.path"}}
Aturan:
1. Untuk tiap endpoint: minimal satu skenario positif, lalu negatif/validasi (field wajib kosong, tipe salah, id tidak ada, tanpa otorisasi) dengan status yang wajar (400/401/404/422).
2. Gunakan capture untuk nilai yang dipakai endpoint lain (mis. id hasil POST → {{wo_id}} pada GET /wo/{{wo_id}}); urutkan test case sesuai ketergantungan.
3. Cek isi respons dengan kind json bila struktur respons diketahui; tambahkan cek waktu respons (time lt 2000) pada skenario positif.
4. Data yang dibuat diawali "<<data_prefix>>". Jangan menulis password/token asli; header otorisasi diisi sistem.
5. Maksimal <<max>> test case."""


class GenerateIn(BaseModel):
    app_id: int
    spec_text: str = Field(min_length=1, max_length=5_000_000)
    profile_id: int | None = None
    focus: str = Field(default="", max_length=2000)  # mis. "fokus endpoint work order"
    max_cases: int = Field(default=30, ge=1, le=100)


@router.post("/api-suites/generate")
def generate_cases(body: GenerateIn, request: Request) -> dict:
    """AI menyusun test case API (positif/negatif/validasi) dari OpenAPI; hasil direview QA sebelum disimpan."""
    from qa_agent.server.api.profiles import client_for

    _app_or_404(request, body.app_id)
    store = deps.store(request)
    profile = store.get_profile(body.profile_id) if body.profile_id else store.get_default_profile()
    if profile is None:
        raise ValueError("Belum ada profil AI. Tambahkan di Pengaturan > Model AI")
    summary = openapi_summary(body.spec_text)
    system = API_PLAN_SYSTEM.replace("<<data_prefix>>", "QA-AUTO").replace("<<max>>", str(body.max_cases))
    text = f"## Endpoint\n{summary}" + (f"\n\n## Fokus dari QA\n{body.focus}" if body.focus.strip() else "")
    try:
        reply = client_for(request, profile).chat(system, [Message(role="user", text=text)])
        data = extract_json(reply)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"Endpoint AI bermasalah: {e}") from e
    except ActionParseError as e:
        raise HTTPException(status_code=502, detail=f"Jawaban AI tidak bisa dibaca: {e}") from e
    cases = []
    for item in (data.get("cases") if isinstance(data, dict) else None) or []:
        try:
            path = str(item.get("path") or item.get("url") or "/")
            url = path if path.startswith(("http://", "https://", "{{")) else "{{base_url}}" + ("" if path.startswith("/") else "/") + path
            body_text = item.get("body") or ""
            if not isinstance(body_text, str):
                body_text = json.dumps(body_text, ensure_ascii=False)
            case = CaseIn(name=item["name"], method=str(item.get("method") or "GET").upper(), url=url,
                          headers=item.get("headers") or {}, body=body_text,
                          assertions=[AssertionIn(**{k: str(v) if k == "expected" else v for k, v in a.items()
                                                     if k in ("kind", "op", "expected", "path")})
                                      for a in item.get("assertions") or []],
                          capture=item.get("capture") or {})
        except Exception:  # noqa: BLE001 - item AI yang tidak valid dilewati
            continue
        cases.append(case.model_dump())
    if not cases:
        raise HTTPException(status_code=502, detail="AI tidak menghasilkan test case yang valid. Coba lagi")
    return {"cases": cases, "base_url": openapi_base_url(body.spec_text)}


class RunIn(BaseModel):
    confirm_production: bool = False


@router.post("/api-suites/{suite_id}/run")
def run_suite(suite_id: int, body: RunIn, request: Request) -> dict:
    suite = _suite_or_404(request, suite_id)
    cfg = suite["config"]
    writes = any(c["method"] in WRITE_METHODS for c in cfg["cases"])
    if cfg.get("environment") == "production" and writes and not body.confirm_production:
        raise HTTPException(status_code=409, detail="Suite ini berisi request yang mengubah data (POST/PUT/PATCH/DELETE) "
                                                    "ke Production. Konfirmasi dulu untuk menjalankan")
    user = getattr(request.state, "user", None)
    return request.app.state.api_runs.start(suite, created_by=user.username if user else None)


@router.get("/api-suites/{suite_id}/runs")
def list_runs(suite_id: int, request: Request) -> list[dict]:
    _suite_or_404(request, suite_id)
    out = []
    for r in deps.store(request).list_api_runs(suite_id):
        summary = (r.get("result") or {}).get("summary")
        out.append({k: v for k, v in r.items() if k not in ("result", "config")} | {"summary": summary})
    return out


@router.get("/api-runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict:
    run = deps.store(request).get_api_run(run_id)
    if run is None:
        raise deps.not_found("Run API")
    if run["status"] == "running":
        partial = request.app.state.api_runs.progress(run_id)
        if partial is not None:
            run["result"] = {"cases": partial, "total": len(run["config"].get("cases", []))}
    return run


@router.post("/api-runs/{run_id}/stop")
def stop_run(run_id: int, request: Request) -> dict:
    if deps.store(request).get_api_run(run_id) is None:
        raise deps.not_found("Run API")
    return {"stopping": request.app.state.api_runs.stop(run_id)}


@router.delete("/api-runs/{run_id}", status_code=204)
def delete_run(run_id: int, request: Request) -> Response:
    run = deps.store(request).get_api_run(run_id)
    if run is None:
        raise deps.not_found("Run API")
    if run["status"] == "running":
        raise HTTPException(status_code=409, detail="Run sedang berjalan. Hentikan dulu")
    deps.store(request).delete_api_run(run_id)
    return Response(status_code=204)


@router.get("/api-runs/{run_id}/xlsx")
def download_xlsx(run_id: int, request: Request) -> Response:
    from qa_agent.server.reporting import KEY_TEMPLATE_SHEET, excel_template, template_fields

    run = deps.store(request).get_api_run(run_id)
    if run is None:
        raise deps.not_found("Run API")
    store, settings = deps.store(request), deps.settings(request)
    app = store.get_app(run["app_id"])
    with tempfile.TemporaryDirectory() as tmp:
        path = api_run_xlsx(run, Path(tmp) / "api.xlsx", template=excel_template(store, settings),
                            fields=template_fields(store), context={"Project": app.name if app else ""},
                            sheet=store.get_setting(KEY_TEMPLATE_SHEET))
        data = path.read_bytes()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="api-test-run{run_id}.xlsx"'})
