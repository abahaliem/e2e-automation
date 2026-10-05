from __future__ import annotations

import base64
import time
from typing import Any

import anthropic

from qa_agent.llm.base import LLMError, LLMTransientError, Message, image_media_type, with_retry


class AnthropicClient:
    """Claude lewat Anthropic Messages API (provider alternatif)."""

    def __init__(self, *, model: str, api_key: str, timeout: int = 60, vision: bool = True, max_tokens: int = 2048,
                 sleep=time.sleep, client: Any = None) -> None:
        self.model = model
        self.vision = vision
        self.max_tokens = max_tokens
        self._sleep = sleep
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)

    def build_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            blocks: list[dict] = []
            if m.images and self.vision and m.role == "user":
                for img in m.images:
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": image_media_type(img), "data": base64.b64encode(img).decode()},
                    })
            blocks.append({"type": "text", "text": m.text})
            out.append({"role": m.role, "content": blocks})
        return out

    def chat(self, system: str, messages: list[Message]) -> str:
        payload = self.build_messages(messages)

        def call() -> str:
            try:
                resp = self._client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system, messages=payload)
            except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
                raise LLMTransientError(str(e)) from e
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    raise LLMTransientError(str(e)) from e
                raise LLMError(f"Claude menolak request ({e.status_code}): {e.message}") from e
            return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")

        return with_retry(call, sleep=self._sleep)
