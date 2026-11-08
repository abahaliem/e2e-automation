from __future__ import annotations

from qa_agent.config import Config, ConfigError
from qa_agent.llm.base import LLMClient


def build_llm(cfg: Config, api_key: str | None = None) -> LLMClient:
    """`api_key` eksplisit (dari dashboard/SecretStore) dipakai alih-alih variabel lingkungan.

    Library openai/anthropic baru dimuat di sini (berat, beberapa detik) supaya `qa-agent serve` cepat menyala.
    """
    llm = cfg.llm
    key = api_key if api_key is not None else cfg.api_key()
    if llm.provider == "anthropic":
        from qa_agent.llm.anthropic_client import AnthropicClient

        return AnthropicClient(model=llm.model, api_key=key, timeout=llm.timeout_seconds, vision=llm.vision)
    if not llm.base_url:
        raise ConfigError("llm.base_url wajib diisi untuk provider openai_compatible")
    from qa_agent.llm.openai_compat import OpenAICompatClient

    return OpenAICompatClient(model=llm.model, api_key=key, base_url=llm.base_url,
                              timeout=llm.timeout_seconds, vision=llm.vision)
