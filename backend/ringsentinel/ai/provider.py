"""LLM provider interface (component C16 side) and the concrete providers.

`LLMProvider.generate()` takes a system prompt and a list of messages and returns text. Nothing
else is required of a provider: the tool loop, the JSON protocol and all checking live in this
package, so Groq, Gemini and test doubles are interchangeable.

Groq and Gemini are called over plain HTTPS with the standard library (no SDK, so no new
dependency). API keys are read from the environment when the provider is built, are sent in
headers (never in a URL) and are never written to an error message or a file.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Model names change often on free tiers; override with RS_LLM_MODEL. Verify on the provider page.
DEFAULT_MODELS = {"groq": "llama-3.3-70b-versatile", "gemini": "gemini-2.5-flash"}
KEY_VARS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
_GROQ_MODEL_RE = re.compile(
    r"^(?=.{1,80}$)(?:[A-Za-z0-9][A-Za-z0-9._:-]{1,39}/)?[A-Za-z0-9][A-Za-z0-9._:-]*$"
)


class ProviderError(Exception):
    """The provider could not answer. `retryable` marks rate limits and server errors."""

    def __init__(self, message: str, *, retryable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(
        self, system: str, messages: Sequence[Message], *, json_mode: bool = True,
        max_tokens: int = 1500, temperature: float = 0.0,
    ) -> str: ...  # fmt: skip


# --------------------------------------------------------------------------- HTTP
Transport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes, Mapping[str, str]]]


def urllib_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, bytes, Mapping[str, str]]:
    request_headers = {
        **dict(headers),
        "User-Agent": "RingSentinel/0.7.0",
}
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method="POST"
)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"network error: {type(exc).__name__}", retryable=True) from None


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None


def _http_json(
    transport: Transport, url: str, headers: dict[str, str], payload: dict, timeout: float
) -> dict:  # fmt: skip
    status, raw, response_headers = transport(url, headers, json.dumps(payload).encode(), timeout)
    if status >= 400:
        detail = raw.decode("utf-8", errors="replace")[:500]
        for name, value in headers.items():
            if name.lower() in {"authorization", "x-goog-api-key"}:
                secret = value.removeprefix("Bearer ").strip()
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")

        message = f"provider answered HTTP {status}"
        if detail:
            message = f"{message}: {detail}"

        if status == 429 or status >= 500:
            raise ProviderError(
                message,
                retryable=True,
                retry_after=_retry_after(response_headers),
            )

        raise ProviderError(message)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("provider returned a body that is not JSON") from None


class GroqProvider:
    """Groq's OpenAI-compatible chat endpoint (free tier; the development provider)."""

    name = "groq"

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODELS["groq"], *, timeout: float = 60.0,
        transport: Transport = urllib_transport,
    ):  # fmt: skip
        if not api_key:
            raise ProviderError("GROQ_API_KEY is not set")
        if not _GROQ_MODEL_RE.match(model):
            raise ProviderError("model name has unexpected characters")
        self._key, self.model, self._timeout, self._transport = api_key, model, timeout, transport

    def generate(self, system, messages, *, json_mode=True, max_tokens=1500, temperature=0.0):
        payload: dict = {
            "model": self.model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }  # fmt: skip
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        if self.model.startswith("openai/gpt-oss-"):
            payload["reasoning_format"] = "hidden"
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        data = _http_json(self._transport, GROQ_URL, headers, payload, self._timeout)
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            raise ProviderError("unexpected response shape from Groq") from None


class GeminiProvider:
    """Google Gemini generateContent (free tier; the production provider)."""

    name = "gemini"

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODELS["gemini"], *, timeout: float = 60.0,
        transport: Transport = urllib_transport,
    ):  # fmt: skip
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        if not _MODEL_RE.match(model):
            raise ProviderError("model name has unexpected characters")
        self._key, self.model, self._timeout, self._transport = api_key, model, timeout, transport

    def generate(self, system, messages, *, json_mode=True, max_tokens=1500, temperature=0.0):
        config: dict = {"temperature": temperature, "maxOutputTokens": max(max_tokens, 2048)}
        if json_mode:
            config["responseMimeType"] = "application/json"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]}
                for m in messages
            ],
            "generationConfig": config,
        }  # fmt: skip
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        data = _http_json(
            self._transport, GEMINI_URL.format(model=self.model), headers, payload, self._timeout
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(str(p.get("text", "")) for p in parts)
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned no usable candidate") from None


# ------------------------------------------------------------------- resilience
class ResilientProvider:
    """Wraps a provider with pacing (free tiers limit requests per minute) and bounded retries."""

    def __init__(
        self, inner: LLMProvider, *, min_interval_s: float = 2.5, max_attempts: int = 3,
        base_backoff_s: float = 5.0, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):  # fmt: skip
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self._min_interval, self._attempts, self._backoff = (
            min_interval_s,
            max_attempts,
            base_backoff_s,
        )
        self._sleep, self._clock = sleep, clock
        self._last: float | None = None
        self.calls = 0

    def generate(self, system, messages, **kwargs):
        last_error: ProviderError | None = None
        for attempt in range(self._attempts):
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            self.calls += 1
            try:
                return self.inner.generate(system, messages, **kwargs)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt == self._attempts - 1:
                    raise
                self._sleep(min(exc.retry_after or self._backoff * (2**attempt), 60.0))
        raise last_error or ProviderError("no attempt was made")  # pragma: no cover


# ------------------------------------------------------------------ test doubles
class ScriptedProvider:
    """Returns prepared replies in order; an Exception in the script is raised instead.

    A reply may also be a function `(system, messages) -> str`. Every call is recorded in
    `calls` so tests can inspect exactly what a prompt contained.
    """

    name = "scripted"
    model = "scripted-1"

    def __init__(self, script: Sequence[str | Exception | Callable[[str, list[Message]], str]]):
        self._script = list(script)
        self.calls: list[tuple[str, list[Message]]] = []

    def generate(self, system, messages, **kwargs):
        self.calls.append((system, list(messages)))
        if not self._script:
            raise ProviderError("scripted provider has no more replies")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(system, list(messages)) if callable(item) else item


class FailingProvider:
    """Always unavailable. Used to test the cache and the template fallback."""

    name = "failing"
    model = "none"

    def __init__(self, message: str = "provider unavailable", retryable: bool = False):
        self._message, self._retryable = message, retryable
        self.calls = 0

    def generate(self, system, messages, **kwargs):
        self.calls += 1
        raise ProviderError(self._message, retryable=self._retryable)


def make_provider(
    name: str, *, model: str | None = None, timeout: float = 60.0, min_interval_s: float = 2.5,
    environ: Mapping[str, str] | None = None, transport: Transport = urllib_transport,
) -> LLMProvider | None:  # fmt: skip
    """Build a provider by name: `none` (offline), `fake`, `groq` or `gemini`."""
    env = os.environ if environ is None else environ
    name = (name or "none").strip().lower()
    if name in ("none", ""):
        return None
    if name == "fake":
        from ringsentinel.ai.fake import HeuristicProvider

        return HeuristicProvider()
    if name not in DEFAULT_MODELS:
        raise ProviderError(f"unknown provider {name!r}; use none, fake, groq or gemini")
    key = env.get(KEY_VARS[name], "").strip()
    cls = GroqProvider if name == "groq" else GeminiProvider
    inner = cls(key, model or DEFAULT_MODELS[name], timeout=timeout, transport=transport)
    return ResilientProvider(inner, min_interval_s=min_interval_s)
