"""Aplikasi > Data uji dan Persiapan otomatis (HTTP)."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from qa_agent.server.api import deps
from qa_agent.server.store import HookRow
from qa_agent.server.testdata import SET_NAME, HookError, hook_secret_key, run_hook

router = APIRouter(prefix="/api", tags=["test-data"])


def _app_or_404(request: Request, app_id: int):
    app = deps.store(request).get_app(app_id)
    if app is None:
        raise deps.not_found("Aplikasi")
    return app


def _sets(request: Request, app_id: int) -> list[dict]:
    groups: dict[str, dict] = {}
    for v in deps.store(request).list_test_data(app_id):
        g = groups.setdefault(v.set_name.lower(), {"name": v.set_name, "values": [], "available": 0})
        g["values"].append(v.model_dump())
        if v.used_by is None:
            g["available"] += 1
    return list(groups.values())


class DataIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    values: str = Field(max_length=50_000)  # satu nilai per baris


@router.get("/apps/{app_id}/test-data")
def list_data(app_id: int, request: Request) -> list[dict]:
    _app_or_404(request, app_id)
    return _sets(request, app_id)


@router.post("/apps/{app_id}/test-data")
def add_data(app_id: int, body: DataIn, request: Request) -> list[dict]:
    _app_or_404(request, app_id)
    name = body.name.strip()
    if not SET_NAME.match(name):
        raise ValueError("name::Nama hanya huruf, angka, garis bawah, titik, atau strip (mis. wo_id)")
    values = [v.strip() for v in body.values.splitlines() if v.strip()]
    if not values:
        raise ValueError("values::Isi minimal satu nilai (satu per baris)")
    deps.store(request).add_test_data(app_id, name, values)
    return _sets(request, app_id)


@router.patch("/test-data/{value_id}")
def reset_value(value_id: int, request: Request) -> dict:
    store = deps.store(request)
    if store.get_test_data(value_id) is None:
        raise deps.not_found("Data uji")
    store.reset_test_data(value_id)  # kembalikan ke "tersedia"
    return store.get_test_data(value_id).model_dump()  # type: ignore[union-attr]


@router.delete("/test-data/{value_id}", status_code=204)
def delete_value(value_id: int, request: Request) -> Response:
    if deps.store(request).get_test_data(value_id) is None:
        raise deps.not_found("Data uji")
    deps.store(request).delete_test_data(value_id)
    return Response(status_code=204)


@router.delete("/apps/{app_id}/test-data/{name}", status_code=204)
def delete_set(app_id: int, name: str, request: Request) -> Response:
    _app_or_404(request, app_id)
    deps.store(request).delete_test_data_set(app_id, name)
    return Response(status_code=204)


# ---------------------------------------------------------------- persiapan HTTP
def _parse_headers(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
        for line in text.splitlines():  # juga terima format "Nama: nilai" per baris
            if ":" not in line:
                raise ValueError("headers::Header berupa JSON atau 'Nama: nilai' per baris")
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ValueError("headers::Header berupa JSON objek berisi teks")
    return data


def _parse_capture(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError("capture::Format: nama_data = path.di.respons (mis. wo_id = data.id)")
        name, path = (p.strip() for p in line.split("=", 1))
        if not SET_NAME.match(name) or not path:
            raise ValueError("capture::Format: nama_data = path.di.respons (mis. wo_id = data.id)")
        out[name] = path
    return out


class HookIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    when: Literal["run", "case"] = "case"
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    url: str = Field(max_length=2000)
    headers: str = Field(default="", max_length=8000)
    body: str = Field(default="", max_length=50_000)
    capture: str = Field(default="", max_length=2000)


class HookPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    when: Literal["run", "case"] | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    url: str | None = Field(default=None, max_length=2000)
    headers: str | None = Field(default=None, max_length=8000)  # None = tidak diubah, "" = hapus header
    body: str | None = Field(default=None, max_length=50_000)
    capture: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


def _check_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("url::URL harus diawali http:// atau https://")
    return url


def _hook_out(request: Request, hook: HookRow) -> dict:
    data = hook.model_dump()
    data["has_headers"] = bool(deps.secrets(request).get(hook_secret_key(hook.id)))
    return data


@router.get("/apps/{app_id}/hooks")
def list_hooks(app_id: int, request: Request) -> list[dict]:
    _app_or_404(request, app_id)
    return [_hook_out(request, h) for h in deps.store(request).list_hooks(app_id)]


@router.post("/apps/{app_id}/hooks", status_code=201)
def create_hook(app_id: int, body: HookIn, request: Request) -> dict:
    _app_or_404(request, app_id)
    headers = _parse_headers(body.headers)
    hook = deps.store(request).create_hook(app_id=app_id, name=body.name, when=body.when, method=body.method,
                                           url=_check_url(body.url), body=body.body, capture=_parse_capture(body.capture))
    if headers:
        deps.secrets(request).set(hook_secret_key(hook.id), json.dumps(headers))
    return _hook_out(request, hook)


@router.patch("/hooks/{hook_id}")
def patch_hook(hook_id: int, body: HookPatch, request: Request) -> dict:
    store = deps.store(request)
    if store.get_hook(hook_id) is None:
        raise deps.not_found("Persiapan")
    fields = body.model_dump(exclude_unset=True, exclude={"headers"})
    if "url" in fields:
        fields["url"] = _check_url(fields["url"])
    if "capture" in fields:
        fields["capture"] = _parse_capture(fields["capture"] or "")
    hook = store.update_hook(hook_id, **fields)
    if body.headers is not None:
        headers = _parse_headers(body.headers)
        if headers:
            deps.secrets(request).set(hook_secret_key(hook_id), json.dumps(headers))
        else:
            deps.secrets(request).delete(hook_secret_key(hook_id))
    return _hook_out(request, hook)


@router.delete("/hooks/{hook_id}", status_code=204)
def delete_hook(hook_id: int, request: Request) -> Response:
    store = deps.store(request)
    if store.get_hook(hook_id) is None:
        raise deps.not_found("Persiapan")
    store.delete_hook(hook_id)
    deps.secrets(request).delete(hook_secret_key(hook_id))
    return Response(status_code=204)


@router.post("/hooks/{hook_id}/test")
def test_hook(hook_id: int, request: Request) -> dict:
    """Coba jalankan persiapan sekarang (sungguhan: data yang dibuat endpoint tetap tercatat di Data uji)."""
    store = deps.store(request)
    hook = store.get_hook(hook_id)
    if hook is None:
        raise deps.not_found("Persiapan")
    try:
        captured = run_hook(store, deps.secrets(request), hook, used_by="Coba dari dashboard")
    except HookError as e:
        return {"ok": False, "message": str(e), "captured": {}}
    return {"ok": True, "message": "Berhasil", "captured": captured}
