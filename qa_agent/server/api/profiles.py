from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from qa_agent.imaging import solid_png
from qa_agent.llm.base import LLMClient, LLMError, Message
from qa_agent.server.api import deps
from qa_agent.server.secrets import mask_secret
from qa_agent.server.store import ProfileRow

router = APIRouter(prefix="/api", tags=["profiles"])
BASE_URL_REQUIRED = "Base URL wajib diisi untuk endpoint OpenAI-compatible"


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str = Field(default="", validate_default=True)
    model: str = Field(min_length=1)
    api_key: str = ""
    vision: bool = True
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    is_default: bool = False

    @field_validator("base_url")
    @classmethod
    def _base_url(cls, v: str, info: ValidationInfo) -> str:
        v = (v or "").strip().rstrip("/")
        if info.data.get("provider", "openai_compatible") == "openai_compatible" and not v:
            raise ValueError(BASE_URL_REQUIRED)
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Base URL harus diawali http:// atau https://")
        return v


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    provider: Literal["openai_compatible", "anthropic"] | None = None
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: str | None = None
    vision: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    is_default: bool | None = None


def _out(request: Request, p: ProfileRow) -> dict:
    key = deps.secrets(request).get(f"ai-profile:{p.id}")
    return {**p.model_dump(), "api_key_masked": mask_secret(key), "has_api_key": bool(key)}


def _get(request: Request, profile_id: int) -> ProfileRow:
    p = deps.store(request).get_profile(profile_id)
    if p is None:
        raise deps.not_found("Profil AI")
    return p


def client_for(request: Request, p: ProfileRow) -> LLMClient:
    factory = request.app.state.llm_factory
    if factory is not None:
        return factory(p)
    key = deps.secrets(request).get(f"ai-profile:{p.id}") or ""
    if p.provider == "anthropic":
        from qa_agent.llm.anthropic_client import AnthropicClient

        return AnthropicClient(model=p.model, api_key=key, timeout=p.timeout_seconds, vision=p.vision)
    from qa_agent.llm.openai_compat import OpenAICompatClient

    return OpenAICompatClient(model=p.model, api_key=key, base_url=p.base_url, timeout=p.timeout_seconds,
                              vision=p.vision)


@router.get("/profiles")
def list_profiles(request: Request) -> list[dict]:
    return [_out(request, p) for p in deps.store(request).list_profiles()]


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileIn, request: Request) -> dict:
    data = body.model_dump(exclude={"api_key"})
    p = deps.store(request).create_profile(**data)
    if body.api_key.strip():
        deps.secrets(request).set(f"ai-profile:{p.id}", body.api_key.strip())
    return _out(request, p)


@router.patch("/profiles/{profile_id}")
def patch_profile(profile_id: int, body: ProfilePatch, request: Request) -> dict:
    current = _get(request, profile_id)
    fields = body.model_dump(exclude_unset=True, exclude={"api_key"})
    if "base_url" in fields:
        fields["base_url"] = (fields["base_url"] or "").strip().rstrip("/")
    merged = {**current.model_dump(), **fields}
    ProfileIn.model_validate({**merged, "api_key": ""})  # validasi gabungan (base URL wajib, dst.)
    p = deps.store(request).update_profile(profile_id, **fields)
    if body.api_key and body.api_key.strip():  # kosong = tidak diganti
        deps.secrets(request).set(f"ai-profile:{p.id}", body.api_key.strip())
    return _out(request, p)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, request: Request) -> Response:
    _get(request, profile_id)
    deps.store(request).delete_profile(profile_id)
    deps.secrets(request).delete(f"ai-profile:{profile_id}")
    return Response(status_code=204)


@router.post("/profiles/{profile_id}/models")
def list_models(profile_id: int, request: Request) -> dict:
    p = _get(request, profile_id)
    if p.provider == "anthropic" or not p.base_url:
        return {"models": [], "message": "Daftar model tidak tersedia untuk provider ini. Ketik nama model manual."}
    key = deps.secrets(request).get(f"ai-profile:{p.id}") or ""
    req = urllib.request.Request(f"{p.base_url}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = sorted({str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")})
        return {"models": models, "message": "" if models else "Endpoint tidak mengembalikan daftar model."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return {"models": [], "message": f"Gagal mengambil daftar model ({reason}). Ketik nama model manual."}


@router.post("/profiles/{profile_id}/test")
def test_profile(profile_id: int, request: Request) -> dict:
    p = _get(request, profile_id)
    started = time.monotonic()
    text_ok = vision_ok = False
    message = ""
    try:
        llm = client_for(request, p)
        reply = llm.chat("Jawab sangat singkat.", [Message(role="user", text="Balas dengan satu kata: OK")])
        text_ok = bool(reply.strip())
        if p.vision:
            reply = llm.chat("Jawab dengan satu kata.", [Message(
                role="user", text="Apa warna gambar ini? Jawab: merah, hijau, atau biru.",
                images=[solid_png((220, 20, 20), (64, 64))])])
            vision_ok = any(w in reply.lower() for w in ("merah", "red"))
            if not vision_ok:
                message = f"Model menjawab '{reply.strip()[:40]}' untuk tes gambar. Matikan 'Bisa membaca gambar' bila model tidak mendukung."
        message = message or "Koneksi berhasil"
    except LLMError as e:
        message = f"Gagal: {e}"
    except Exception as e:
        message = f"Gagal: {type(e).__name__}: {e}"
    return {"text_ok": text_ok, "vision_ok": vision_ok, "latency_ms": int((time.monotonic() - started) * 1000),
            "message": message}
