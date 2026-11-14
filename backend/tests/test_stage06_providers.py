"""Groq and Gemini providers with a fake transport: requests, parsing, errors, key handling."""

import json

import pytest
from ringsentinel.ai.provider import (
    DEFAULT_MODELS,
    GeminiProvider,
    GroqProvider,
    Message,
    ProviderError,
    ResilientProvider,
    make_provider,
)

KEY = "sk-test-SECRET-1234567890"


class Transport:
    def __init__(self, status=200, body=None, headers=None):
        self.status, self.body, self.headers = status, body, headers or {}
        self.requests: list[tuple[str, dict, dict, float]] = []

    def __call__(self, url, headers, data, timeout):
        self.requests.append((url, dict(headers), json.loads(data), timeout))
        raw = json.dumps(self.body).encode() if not isinstance(self.body, bytes) else self.body
        return self.status, raw, self.headers


GROQ_OK = {"choices": [{"message": {"content": '{"type": "case_file"}'}}]}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": '{"a": '}, {"text": "1}"}]}}]}
MSGS = [Message("user", "hello"), Message("assistant", "hi"), Message("user", "again")]


def test_groq_request_shape_and_parsing():
    t = Transport(body=GROQ_OK)
    out = GroqProvider(KEY, "m-1", timeout=12, transport=t).generate("SYS", MSGS, max_tokens=99)
    assert out == '{"type": "case_file"}'
    url, headers, payload, timeout = t.requests[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions" and timeout == 12
    assert headers["Authorization"] == f"Bearer {KEY}" and KEY not in url
    assert payload["model"] == "m-1" and payload["max_tokens"] == 99
    assert payload["response_format"] == {"type": "json_object"} and payload["temperature"] == 0.0
    assert [m["role"] for m in payload["messages"]] == ["system", "user", "assistant", "user"]
    plain = Transport(body=GROQ_OK)
    GroqProvider(KEY, transport=plain).generate("S", MSGS, json_mode=False)
    assert "response_format" not in plain.requests[0][2]


def test_gemini_request_shape_and_parsing():
    t = Transport(body=GEMINI_OK)
    out = GeminiProvider(KEY, "gemini-x", transport=t).generate("SYS", MSGS)
    assert out == '{"a": 1}'
    url, headers, payload, _ = t.requests[0]
    assert url.endswith("/models/gemini-x:generateContent") and KEY not in url
    assert headers["x-goog-api-key"] == KEY
    assert payload["system_instruction"]["parts"][0]["text"] == "SYS"
    assert [c["role"] for c in payload["contents"]] == ["user", "model", "user"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("cls", [GroqProvider, GeminiProvider])
@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (500, True), (503, True), (400, False), (401, False)]
)
def test_http_errors_are_classified_and_never_leak_the_key(cls, status, retryable):
    t = Transport(status=status, body={"error": {"message": f"bad key {KEY}"}})
    with pytest.raises(ProviderError) as info:
        cls(KEY, transport=t).generate("S", MSGS)
    assert info.value.retryable is retryable
    assert KEY not in str(info.value) and str(status) in str(info.value)


def test_retry_after_header_is_read():
    t = Transport(status=429, body={}, headers={"Retry-After": "12"})
    with pytest.raises(ProviderError) as info:
        GroqProvider(KEY, transport=t).generate("S", MSGS)
    assert info.value.retry_after == 12.0
def test_rate_limit_details_are_preserved_without_leaking_key():
    body = {
        "error": {
            "message": f"Rate limit exceeded for key {KEY}"
        }
    }
    t = Transport(status=429, body=body)

    with pytest.raises(ProviderError) as info:
        GroqProvider(KEY, transport=t).generate("S", MSGS)

    assert "HTTP 429" in str(info.value)
    assert "Rate limit exceeded" in str(info.value)
    assert KEY not in str(info.value)
    assert info.value.retryable is True


@pytest.mark.parametrize("cls", [GroqProvider, GeminiProvider])
@pytest.mark.parametrize("body", [{}, {"choices": []}, {"candidates": []}, b"<html>", []])
def test_unexpected_bodies_are_provider_errors(cls, body):
    with pytest.raises(ProviderError):
        cls(KEY, transport=Transport(body=body)).generate("S", MSGS)


@pytest.mark.parametrize("cls", [GroqProvider, GeminiProvider])
def test_missing_key_and_odd_model_names_are_refused(cls):
    with pytest.raises(ProviderError):
        cls("", transport=Transport())
    for model in ("../x", "a b", "x?key=1", "", "a" * 200, "m/odel"):
        with pytest.raises(ProviderError):
            cls(KEY, model, transport=Transport())


def test_make_provider_reads_keys_from_the_environment_only():
    assert make_provider("none") is None and make_provider("") is None
    fake = make_provider("fake")
    assert fake.name == "fake"
    groq = make_provider("groq", environ={"GROQ_API_KEY": KEY})
    assert isinstance(groq, ResilientProvider) and groq.name == "groq"
    assert groq.model == DEFAULT_MODELS["groq"]
    assert (
        make_provider("gemini", model="gemini-z", environ={"GEMINI_API_KEY": KEY}).model
        == "gemini-z"
    )
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        make_provider("groq", environ={})
    with pytest.raises(ProviderError, match="unknown provider"):
        make_provider("openai", environ={})
    assert KEY not in repr(vars(groq.inner).get("name", ""))
