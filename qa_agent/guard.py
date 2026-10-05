from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

from qa_agent.models import Action, Element, GuardDecision, Risk

RISKY_KEYWORDS: tuple[str, ...] = (
    "hapus", "delete", "remove", "bayar", "pay", "checkout", "kirim", "send", "submit",
    "simpan", "save", "update", "approve", "setujui", "reject", "tolak", "transfer",
    "nonaktifkan", "deactivate", "reset", "konfirmasi", "confirm", "upload", "import", "broadcast",
)
LOGOUT_KEYWORDS: tuple[str, ...] = ("logout", "log out", "sign out", "signout", "keluar")
LOGIN_SEGMENTS = {"login", "signin", "sign-in", "auth", "token", "session", "sessions"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _has_word(text: str, words: Iterable[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words)


def _blocked(reason: str, risk: Risk = "high") -> GuardDecision:
    return GuardDecision(allowed=False, risk=risk, reason=reason)


class Guard:
    def __init__(
        self,
        environment: str,
        allowed_domains: Iterable[str],
        *,
        extra_keywords: Iterable[str] = (),
        login_endpoints: Iterable[str] = (),
    ) -> None:
        self.environment = environment
        self.allowed_domains = [d.lower() for d in allowed_domains if d]
        self.keywords = RISKY_KEYWORDS + tuple(k.lower() for k in extra_keywords)
        self.login_endpoints = [e.lower() for e in login_endpoints]

    @property
    def production(self) -> bool:
        return self.environment == "production"

    def is_allowed_url(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme == "javascript":
            return True
        if not parts.scheme and not parts.netloc:
            return True  # URL relatif
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.allowed_domains)

    def keyword_risk(self, element: Element | None) -> Risk:
        if element is None:
            return "low"
        text = f"{element.name} {element.context}".lower()
        return "high" if _has_word(text, self.keywords) else "low"

    def _is_logout(self, element: Element) -> bool:
        href_path = urlsplit(element.href or "").path.lower()
        return _has_word(element.name.lower(), LOGOUT_KEYWORDS) or "logout" in href_path

    def check(
        self,
        action: Action,
        element: Element | None,
        *,
        explore: bool = False,
        allow_logout: bool = False,
        login: bool = False,
    ) -> GuardDecision:
        kind = action.action
        if kind == "navigate":
            if not action.value or not self.is_allowed_url(action.value):
                return _blocked(f"URL di luar domain yang diizinkan: {action.value}")
            return GuardDecision(allowed=True, risk=action.risk)

        if kind in ("click", "select") and element is not None:
            if element.href and not self.is_allowed_url(element.href):
                return _blocked("Link mengarah ke luar domain yang diizinkan")
            if not allow_logout and self._is_logout(element):
                return _blocked("Aksi logout diblok (test case ini bukan tentang logout)", "medium")

        keyword = self.keyword_risk(element) if kind in ("click", "select") and not login else "low"
        risk: Risk = max(keyword, action.risk, key=_RISK_ORDER.__getitem__)

        if explore:
            if kind in ("type", "select"):
                return _blocked("Mode explore hanya navigasi: tidak mengisi form", "medium")
            if kind == "click" and risk != "low":
                return _blocked("Mode explore tidak mengklik elemen berisiko", risk)

        if self.production and risk == "high":
            return _blocked("Mode production: aksi berisiko tinggi (mengubah data) diblok")
        return GuardDecision(allowed=True, risk=risk)

    def should_block_request(self, method: str, url: str) -> bool:
        if not self.production or method.upper() in SAFE_METHODS:
            return False
        path = urlsplit(url).path.lower()
        if self.login_endpoints:
            return not any(ep in path for ep in self.login_endpoints)
        segments = {s for s in path.split("/") if s}
        return not (segments & LOGIN_SEGMENTS)
