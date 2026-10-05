from __future__ import annotations

from typing import Callable

from qa_agent.llm.base import LLMError, Message

Responder = Callable[[str, list[Message]], str]


class FakeLLM:
    """AI palsu untuk test: daftar jawaban terskrip atau fungsi (system, messages) -> str."""

    model = "fake"

    def __init__(self, responses: list[str] | Responder) -> None:
        self._responder: Responder | None = responses if callable(responses) else None
        self._queue: list[str] = [] if callable(responses) else list(responses)
        self.calls: list[tuple[str, list[Message]]] = []

    def chat(self, system: str, messages: list[Message]) -> str:
        self.calls.append((system, list(messages)))
        if self._responder is not None:
            return self._responder(system, messages)
        if not self._queue:
            raise LLMError("FakeLLM kehabisan jawaban terskrip")
        return self._queue.pop(0)
