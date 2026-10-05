from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol, TypeVar


@dataclass
class Message:
    role: Literal["user", "assistant"]
    text: str
    images: list[bytes] = field(default_factory=list)


class LLMError(Exception):
    """Kesalahan dari endpoint AI yang tidak bisa diulang (mis. API key salah)."""


class LLMTransientError(LLMError):
    """Kesalahan sementara: timeout, 5xx, rate limit."""


class LLMUnavailable(LLMError):
    """Endpoint AI tetap gagal setelah semua retry."""


class LLMClient(Protocol):
    model: str

    def chat(self, system: str, messages: list[Message]) -> str: ...


T = TypeVar("T")
RETRY_DELAYS: tuple[int, ...] = (2, 4, 8)


def with_retry(fn: Callable[[], T], *, delays: tuple[int, ...] = RETRY_DELAYS, sleep: Callable[[float], None] = time.sleep) -> T:
    last: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except LLMTransientError as e:
            last = e
            if attempt < len(delays):
                sleep(delays[attempt])
    raise LLMUnavailable(f"Endpoint AI tidak merespons setelah {len(delays) + 1} percobaan: {last}") from last


def image_media_type(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
