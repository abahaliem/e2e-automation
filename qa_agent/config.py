from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator


class ConfigError(Exception):
    """Config tidak valid atau variabel lingkungan belum diisi."""


class TargetCfg(BaseModel):
    platform: Literal["web", "android"] = "web"
    url: str  # web: http(s)://...; android: android://<nama.paket>
    allowed_domains: list[str] = Field(default_factory=list)
    login_endpoints: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _url_has_scheme(cls, v: str, info: ValidationInfo) -> str:
        if info.data.get("platform") == "android":
            if not re.fullmatch(r"android://[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+/?", v):
                raise ValueError("untuk Android harus berbentuk android://nama.paket.aplikasi")
            return v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("harus diawali http:// atau https://")
        return v.rstrip("/")

    @property
    def package(self) -> str:
        return urlsplit(self.url).netloc if self.platform == "android" else ""


class AccountCfg(BaseModel):
    role: str
    username_env: str
    password_env: str


class LLMCfg(BaseModel):
    provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str | None = None
    model: str
    api_key_env: str
    vision: bool = True
    timeout_seconds: int = 60


class LimitsCfg(BaseModel):
    max_steps_per_tc: int = 25
    deep_max_tcs: int = 15
    explore_max_screens: int = 60
    explore_max_depth: int = 5
    explore_max_minutes: int = 45


class GuardCfg(BaseModel):
    extra_risky_keywords: list[str] = Field(default_factory=list)


class BrowserCfg(BaseModel):
    headless: bool = False
    viewport: str = "1366x768"

    @field_validator("viewport")
    @classmethod
    def _viewport_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d+x\d+", v.strip().lower()):
            raise ValueError("format harus LEBARxTINGGI, contoh 1366x768")
        return v.strip().lower()

    @property
    def size(self) -> tuple[int, int]:
        width, height = self.viewport.split("x")
        return int(width), int(height)


class Credentials(BaseModel):
    role: str
    username: str
    password: str


class Config(BaseModel):
    target: TargetCfg
    environment: Literal["dev", "production"] = "dev"
    accounts: list[AccountCfg]
    llm: LLMCfg
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    guard: GuardCfg = Field(default_factory=GuardCfg)
    browser: BrowserCfg = Field(default_factory=BrowserCfg)

    @field_validator("accounts")
    @classmethod
    def _at_least_one_account(cls, v: list[AccountCfg]) -> list[AccountCfg]:
        if not v:
            raise ValueError("minimal satu akun")
        return v

    def domains(self) -> list[str]:
        if self.target.platform == "android":
            return [self.target.package]
        return self.target.allowed_domains or [urlsplit(self.target.url).hostname or ""]

    def credentials(self, role: str | None = None) -> Credentials:
        if role is None:
            account = self.accounts[0]
        else:
            account = next((a for a in self.accounts if a.role == role), None)
            if account is None:
                raise ConfigError(f"Akun dengan role '{role}' tidak ada di config")
        return Credentials(
            role=account.role,
            username=_env(account.username_env),
            password=_env(account.password_env),
        )

    def api_key(self) -> str:
        return _env(self.llm.api_key_env)


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(f"Variabel lingkungan {name} belum diisi (cek file .env)")
    return value


def load_config(path: Path, env_file: Path | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"File config {path} tidak ditemukan. Jalankan 'qa-agent init' dulu.")
    env_files = [env_file] if env_file else [Path.cwd() / ".env", path.parent / ".env"]
    for candidate in env_files:
        load_dotenv(candidate, override=False)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML tidak valid di {path}: {e}") from e
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        lines = [f"- {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ConfigError("Config tidak valid:\n" + "\n".join(lines)) from e
