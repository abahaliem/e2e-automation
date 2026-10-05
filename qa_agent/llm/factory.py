from __future__ import annotations

from qa_agent.config import Config, ConfigError
from qa_agent.llm.anthropic_client import AnthropicClient
from qa_agent.llm.base import LLMClient
from qa_agent.llm.openai_compat import OpenAICompatClient


def build_llm(cfg: Config) -> LLMClient:
    llm = cfg.llm
    if llm.provider == "anthropic":
        return AnthropicClient(model=llm.model, api_key=cfg.api_key(), timeout=llm.timeout_seconds, vision=llm.vision)
    if not llm.base_url:
        raise ConfigError("llm.base_url wajib diisi untuk provider openai_compatible")
    return OpenAICompatClient(model=llm.model, api_key=cfg.api_key(), base_url=llm.base_url,
                              timeout=llm.timeout_seconds, vision=llm.vision)
