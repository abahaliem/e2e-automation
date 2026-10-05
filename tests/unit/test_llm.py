from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from qa_agent.config import Config, ConfigError
from qa_agent.llm.anthropic_client import AnthropicClient
from qa_agent.llm.base import LLMError, LLMTransientError, LLMUnavailable, Message, image_media_type, with_retry
from qa_agent.llm.factory import build_llm
from qa_agent.llm.fake import FakeLLM
from qa_agent.llm.openai_compat import OpenAICompatClient

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 10
JPEG = b"\xff\xd8\xff" + b"0" * 10
REQ = httpx2.Request("POST", "http://ai.test/v1/chat/completions")


def openai_stub(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_with_retry_retries_then_succeeds():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise LLMTransientError("timeout")
        return "ok"

    assert with_retry(fn, sleep=sleeps.append) == "ok"
    assert sleeps == [2, 4]


def test_with_retry_gives_up_after_three_retries():
    sleeps = []

    def fn():
        raise LLMTransientError("503")

    with pytest.raises(LLMUnavailable, match="4 percobaan"):
        with_retry(fn, sleep=sleeps.append)
    assert sleeps == [2, 4, 8]


def test_image_media_type():
    assert image_media_type(PNG) == "image/png"
    assert image_media_type(JPEG) == "image/jpeg"


def test_openai_builds_vision_payload():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return reply('{"action": "back"}')

    client = OpenAICompatClient(model="z-ai/glm-5.3-flash", api_key="k", base_url="http://ai.test/v1", client=openai_stub(create))
    out = client.chat("SYS", [Message("user", "layar", images=[PNG])])
    assert out == '{"action": "back"}'
    assert seen["model"] == "z-ai/glm-5.3-flash"
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    parts = seen["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "layar"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_text_only_when_vision_disabled():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return reply("x")

    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", vision=False, client=openai_stub(create))
    client.chat("SYS", [Message("user", "layar", images=[PNG])])
    assert seen["messages"][1] == {"role": "user", "content": "layar"}


def test_openai_connection_error_is_retried():
    attempts = []

    def create(**kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise openai.APIConnectionError(request=REQ)
        return reply("pulih")

    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", sleep=lambda s: None, client=openai_stub(create))
    assert client.chat("SYS", [Message("user", "hi")]) == "pulih"
    assert len(attempts) == 2


def test_openai_none_content_becomes_empty_string():
    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", client=openai_stub(lambda **kw: reply(None)))
    assert client.chat("SYS", [Message("user", "hi")]) == ""


def test_anthropic_payload_and_text_join():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ha"), SimpleNamespace(type="text", text="lo")])

    stub = SimpleNamespace(messages=SimpleNamespace(create=create))
    client = AnthropicClient(model="claude-sonnet-5-5", api_key="k", client=stub)
    assert client.chat("SYS", [Message("user", "layar", images=[PNG])]) == "halo"
    assert seen["system"] == "SYS"
    blocks = seen["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[-1] == {"type": "text", "text": "layar"}


def test_anthropic_connection_error_exhausts_to_unavailable():
    def create(**kw):
        raise anthropic.APIConnectionError(request=REQ)

    stub = SimpleNamespace(messages=SimpleNamespace(create=create))
    client = AnthropicClient(model="m", api_key="k", sleep=lambda s: None, client=stub)
    with pytest.raises(LLMUnavailable):
        client.chat("SYS", [Message("user", "hi")])


def test_fake_llm_list_and_callable():
    fake = FakeLLM(["a", "b"])
    assert fake.chat("s", [Message("user", "1")]) == "a"
    assert fake.chat("s", [Message("user", "2")]) == "b"
    with pytest.raises(LLMError, match="kehabisan"):
        fake.chat("s", [Message("user", "3")])
    assert len(fake.calls) == 3
    echo = FakeLLM(lambda system, messages: messages[-1].text.upper())
    assert echo.chat("s", [Message("user", "halo")]) == "HALO"


def cfg(**llm):
    base = {"model": "m", "api_key_env": "LLM_TEST_KEY"}
    return Config.model_validate({
        "target": {"url": "http://app.test"},
        "accounts": [{"role": "a", "username_env": "U", "password_env": "P"}],
        "llm": {**base, **llm},
    })


def test_factory(monkeypatch):
    monkeypatch.setenv("LLM_TEST_KEY", "k")
    assert isinstance(build_llm(cfg(base_url="http://ai.test/v1")), OpenAICompatClient)
    assert isinstance(build_llm(cfg(provider="anthropic")), AnthropicClient)
    with pytest.raises(ConfigError, match="base_url"):
        build_llm(cfg())
