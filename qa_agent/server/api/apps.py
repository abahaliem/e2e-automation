from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator

from qa_agent.server.api import deps
from qa_agent.server.store import AccountRow, AppRow

router = APIRouter(prefix="/api", tags=["apps"])


def _clean_list(values: list[str] | None) -> list[str]:
    return [v.strip() for v in (values or []) if v and v.strip()]


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: Literal["web", "android"] = "web"
    url: str
    allowed_domains: list[str] = Field(default_factory=list)
    login_endpoints: list[str] = Field(default_factory=list)
    default_profile_id: int | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL harus diawali http:// atau https://")
        return v.rstrip("/")


class AppPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = None
    allowed_domains: list[str] | None = None
    login_endpoints: list[str] | None = None
    default_profile_id: int | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else AppIn._url(v)


class AccountIn(BaseModel):
    role: str = Field(min_length=1, max_length=60)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1)


class AccountPatch(BaseModel):
    password: str = Field(min_length=1)


class AccountOut(BaseModel):
    id: int
    app_id: int
    role: str
    username: str
    has_password: bool


def _app_out(request: Request, app: AppRow) -> dict:
    store = deps.store(request)
    explore = store.latest_completed_explore(app.id)
    runs = store.list_runs(app_id=app.id, limit=1)
    return {**app.model_dump(), "explored": explore is not None,
            "last_run_at": runs[0].started_at if runs else None,
            "accounts": len(store.list_accounts(app.id))}


def _account_out(request: Request, acc: AccountRow) -> AccountOut:
    return AccountOut(**acc.model_dump(), has_password=bool(deps.secrets(request).get(f"account:{acc.id}")))


@router.get("/apps")
def list_apps(request: Request) -> list[dict]:
    return [_app_out(request, a) for a in deps.store(request).list_apps()]


@router.post("/apps", status_code=201)
def create_app_(body: AppIn, request: Request) -> dict:
    data = body.model_dump()
    data["allowed_domains"] = _clean_list(body.allowed_domains)
    data["login_endpoints"] = _clean_list(body.login_endpoints)
    return _app_out(request, deps.store(request).create_app(**data))


@router.get("/apps/{app_id}")
def get_app(app_id: int, request: Request) -> dict:
    app = deps.store(request).get_app(app_id)
    if app is None:
        raise deps.not_found("Aplikasi")
    return _app_out(request, app)


@router.patch("/apps/{app_id}")
def patch_app(app_id: int, body: AppPatch, request: Request) -> dict:
    store = deps.store(request)
    if store.get_app(app_id) is None:
        raise deps.not_found("Aplikasi")
    fields = body.model_dump(exclude_unset=True)
    for key in ("allowed_domains", "login_endpoints"):
        if key in fields:
            fields[key] = _clean_list(fields[key])
    return _app_out(request, store.update_app(app_id, **fields))


@router.delete("/apps/{app_id}", status_code=204)
def delete_app(app_id: int, request: Request) -> Response:
    store = deps.store(request)
    if store.get_app(app_id) is None:
        raise deps.not_found("Aplikasi")
    accounts = store.list_accounts(app_id)
    store.delete_app(app_id)  # ValueError → 409 bila sudah punya run
    for acc in accounts:
        deps.secrets(request).delete(f"account:{acc.id}")
    return Response(status_code=204)


@router.get("/apps/{app_id}/modules")
def app_modules(app_id: int, request: Request) -> dict:
    if deps.store(request).get_app(app_id) is None:
        raise deps.not_found("Aplikasi")
    modules = deps.manager(request).modules(app_id)
    explored = deps.store(request).latest_completed_explore(app_id) is not None
    return {"modules": modules, "explored": explored}


@router.get("/apps/{app_id}/accounts")
def list_accounts(app_id: int, request: Request) -> list[AccountOut]:
    if deps.store(request).get_app(app_id) is None:
        raise deps.not_found("Aplikasi")
    return [_account_out(request, a) for a in deps.store(request).list_accounts(app_id)]


@router.post("/apps/{app_id}/accounts", status_code=201)
def create_account(app_id: int, body: AccountIn, request: Request) -> AccountOut:
    store = deps.store(request)
    if store.get_app(app_id) is None:
        raise deps.not_found("Aplikasi")
    acc = store.create_account(app_id=app_id, role=body.role.strip(), username=body.username.strip())
    try:
        deps.secrets(request).set(f"account:{acc.id}", body.password)
    except Exception:
        store.delete_account(acc.id)  # jangan tinggalkan akun tanpa password
        raise
    return _account_out(request, acc)


@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch, request: Request) -> AccountOut:
    acc = deps.store(request).get_account(account_id)
    if acc is None:
        raise deps.not_found("Akun")
    deps.secrets(request).set(f"account:{acc.id}", body.password)
    return _account_out(request, acc)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, request: Request) -> Response:
    store = deps.store(request)
    if store.get_account(account_id) is None:
        raise deps.not_found("Akun")
    store.delete_account(account_id)
    deps.secrets(request).delete(f"account:{account_id}")
    return Response(status_code=204)
