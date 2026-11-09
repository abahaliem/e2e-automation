"""Login, keluar, ganti password sendiri, dan kelola pengguna (mode server)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from qa_agent.server import auth
from qa_agent.server.api import deps
from qa_agent.server.store import UserRow

router = APIRouter(prefix="/api", tags=["auth"])


def user_out(user: UserRow) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


def _check_password(value: str) -> str:
    if len(value) < auth.MIN_PASSWORD:
        raise ValueError(f"Password minimal {auth.MIN_PASSWORD} karakter")
    return value


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class PasswordIn(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)

    @field_validator("new")
    @classmethod
    def _new(cls, v: str) -> str:
        return _check_password(v)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(max_length=256)
    role: Literal["admin", "qa", "viewer"] = "qa"

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _check_password(v)


class UserPatch(BaseModel):
    role: Literal["admin", "qa", "viewer"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, max_length=256)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str | None) -> str | None:
        return None if v is None else _check_password(v)


def current_user(request: Request) -> UserRow | None:
    return getattr(request.state, "user", None)


@router.get("/auth/status")
def status(request: Request) -> dict:
    settings = deps.settings(request)
    if not settings.auth_required:
        return {"auth_required": False, "user": None}
    user = deps.store(request).session_user(request.cookies.get(auth.COOKIE))
    return {"auth_required": True, "user": user_out(user) if user else None}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    settings = deps.settings(request)
    if not settings.auth_required:
        raise HTTPException(status_code=400, detail="Login tidak dipakai di mode lokal")
    limiter: auth.LoginLimiter = request.app.state.login_limiter
    if limiter.blocked(body.username):
        raise HTTPException(status_code=429, detail="Terlalu banyak percobaan gagal. Coba lagi dalam 5 menit")
    store = deps.store(request)
    user = store.get_user_by_name(body.username)
    if user is None or not auth.verify_password(body.password, user.password_hash) or not user.active:
        limiter.fail(body.username)
        raise HTTPException(status_code=401, detail="Username atau password salah, atau akun nonaktif")
    limiter.reset(body.username)
    store.delete_session(request.cookies.get(auth.COOKIE))
    token = store.create_session(user.id, ttl_seconds=auth.SESSION_TTL, max_age_seconds=auth.SESSION_MAX_AGE)
    from qa_agent.evidence import now_iso

    store.update_user(user.id, last_login=now_iso())
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax",
                        secure=settings.secure_cookies, path="/")
    return {"user": user_out(user)}


@router.post("/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    deps.store(request).delete_session(request.cookies.get(auth.COOKIE))
    resp = Response(status_code=204)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordIn, request: Request) -> Response:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=400, detail="Ganti password hanya di mode server")
    if not auth.verify_password(body.current, user.password_hash):
        raise ValueError("current::Password saat ini salah")
    deps.store(request).update_user(user.id, password_hash=auth.hash_password(body.new))
    return Response(status_code=204)


# ---------------------------------------------------------------- kelola pengguna (Admin)
def _user_or_404(request: Request, user_id: int) -> UserRow:
    user = deps.store(request).get_user(user_id)
    if user is None:
        raise deps.not_found("Pengguna")
    return user


def _ensure_admin_remains(request: Request, user: UserRow) -> None:
    if user.role == "admin" and user.active and deps.store(request).count_active_admins() <= 1:
        raise HTTPException(status_code=409, detail="Minimal harus ada satu Admin aktif")


@router.get("/users")
def list_users(request: Request) -> list[dict]:
    return [u.model_dump() for u in deps.store(request).list_users()]


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request) -> dict:
    store = deps.store(request)
    if store.get_user_by_name(body.username):
        raise ValueError(f"username::Username '{body.username}' sudah dipakai")
    return store.create_user(username=body.username, password_hash=auth.hash_password(body.password),
                             role=body.role).model_dump()


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request) -> dict:
    store = deps.store(request)
    user = _user_or_404(request, user_id)
    fields: dict = {}
    if body.role is not None and body.role != user.role:
        if body.role != "admin":
            _ensure_admin_remains(request, user)
        fields["role"] = body.role
    if body.active is not None and body.active != user.active:
        if not body.active:
            _ensure_admin_remains(request, user)
        fields["active"] = body.active
    if body.password is not None:
        fields["password_hash"] = auth.hash_password(body.password)
    updated = store.update_user(user_id, **fields)
    if "active" in fields and not body.active or "password_hash" in fields:
        store.delete_user_sessions(user_id)  # paksa login ulang
    return updated.model_dump()


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request) -> Response:
    user = _user_or_404(request, user_id)
    _ensure_admin_remains(request, user)
    deps.store(request).delete_user(user_id)
    return Response(status_code=204)
