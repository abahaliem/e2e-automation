from __future__ import annotations

import base64
import time
from typing import Any

import openai

from qa_agent.llm.base import LLMError, LLMTransientError, Message, image_media_type, with_retry


class OpenAICompatClient:
    """Endpoint yang kompatibel dengan OpenAI Chat Completions (AI kantor: GLM, DeepSeek, MiniMax)."""

    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: int = 60, vision: bool = True,
                 sleep=time.sleep, client: Any = None) -> None:
        self.model = model
        self.vision = vision
        self._sleep = sleep
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def build_messages(self, system: str, messages: list[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.images and self.vision and m.role == "user":
                parts: list[dict] = [{"type": "text", "text": m.text}]
                for img in m.images:
                    url = f"data:{image_media_type(img)};base64,{base64.b64encode(img).decode()}"
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.text})
        return out

    def chat(self, system: str, messages: list[Message]) -> str:
        payload = self.build_messages(system, messages)

        def call() -> str:
            try:
                resp = self._client.chat.completions.create(model=self.model, messages=payload, temperature=0.2)
            except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
                raise LLMTransientError(str(e)) from e
            except openai.APIStatusError as e:
                if e.status_code >= 500:
                    raise LLMTransientError(str(e)) from e
                raise LLMError(f"Endpoint AI menolak request ({e.status_code}): {e.message}") from e
            if not resp.choices:
                raise LLMTransientError("Respons AI tanpa choices")
            return resp.choices[0].message.content or ""

        return with_retry(call, sleep=self._sleep)
