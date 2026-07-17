"""Homegrown LLM client with health-aware provider fallback.

No external agent framework. Each provider is called through an OpenAI-compatible
`/chat/completions` HTTP interface (OpenAI, Groq, OpenRouter, and local Ollama all
expose this). Providers are tried in the configured order; a provider that errors
out is marked unhealthy (cooldown) and skipped on the next attempt.
"""

from dataclasses import dataclass, field
import httpx
import time
from typing import Optional

from backend.config import get_settings, ProviderName
from backend import _llm_post

OpenAIChatMessage = dict  # {"role": "system"|"user"|"assistant", "content": str}


@dataclass
class _ProviderHealth:
    failures: int = 0
    cooldown_until: float = 0.0


# Health is tracked PER (provider, model), NOT per provider. OpenRouter is a single HTTP
# endpoint that hosts many different models (DeepSeek, Kimi, Aion, Qwen, ...). A single
# model being throttled / rate-limited must NOT cool down the whole OpenRouter gateway and
# take down every other model on it — that previously killed entire Editorial runs the
# moment one panel member hiccupped ("Provider unhealthy (cooldown): openrouter").
_HealthKey = tuple[str, str]


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


# Reasonable per-provider default models.
DEFAULT_MODELS: dict[ProviderName, str] = {
    "openai": "gpt-5.6-luna",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "openai/gpt-4.1-mini",
    "ollama": "qwen3.5:latest",
}

BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    # ollama base url comes from env
}


class LLMClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._order: list[ProviderName] = [
            p.strip() for p in self._settings.llm_provider_order.split(",") if p.strip()
        ]
        self._health: dict[_HealthKey, _ProviderHealth] = {}
        # Generous timeout: Fusion judge calls + long/slow model outputs (esp. on
        # OpenRouter free/economic tiers) routinely exceed the default 60s, which
        # caused run failures ("run failed") on perfectly good requests. Read=180s
        # covers a slow but live completion; connect=20s avoids hanging on DNS.
        self._client = httpx.Client(timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=10.0))

    def _api_key(self, provider: ProviderName) -> Optional[str]:
        keys = {
            "openai": self._settings.openai_api_key,
            "groq": self._settings.groq_api_key,
            "openrouter": self._settings.openrouter_api_key,
        }
        return keys.get(provider) or None

    def _base_url(self, provider: ProviderName) -> Optional[str]:
        if provider == "ollama":
            url = self._settings.ollama_base_url
            return url or None
        return BASE_URLS.get(provider)

    def _is_healthy(self, provider: ProviderName, model: str = "") -> bool:
        h = self._health.get((provider, model))
        if h is None:
            return True
        if h.cooldown_until and time.time() < h.cooldown_until:
            return False
        return True

    def _mark_failure(self, provider: ProviderName, model: str = "") -> None:
        key = (provider, model)
        h = self._health.get(key) or _ProviderHealth()
        h.failures += 1
        # Only cool down THIS model (not the whole provider/gateway). A model needs 2
        # consecutive failures before a short 20s cooldown so a hard-throttled model is
        # skipped transiently without killing sibling models on the same provider.
        if h.failures >= 2:
            h.cooldown_until = time.time() + 20  # 20s cooldown (per model)
        self._health[key] = h

    def _payload(self, provider: str, model: str, messages, temperature: float, max_tokens: int) -> dict:
        """Build the chat/completions body with the provider-correct token param.

        OpenAI's current models (gpt-5.x) REJECT `max_tokens` with a 400 and require
        `max_completion_tokens`. OpenRouter/Ollama still use `max_tokens`. Sending the
        wrong key is why every OpenAI call was 400ing — so OpenAI was never a usable
        fallback when OpenRouter stalled (we just paid for dead OpenRouter calls)."""
        body = {
            "model": model,
            "messages": messages,
        }
        if provider == "openai":
            # gpt-5.x rejects `max_tokens` (needs `max_completion_tokens`) AND a custom
            # `temperature` (reasoning models use the default). Sending either 400s the
            # call — which is why OpenAI was never a usable fallback and we kept paying
            # for dead OpenRouter stalls.
            body["max_completion_tokens"] = max_tokens
        else:
            body["temperature"] = temperature
            body["max_tokens"] = max_tokens
        return body

    def complete(
        self,
        messages: list[OpenAIChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        last_error: Optional[Exception] = None
        for provider in self._order:
            if not self._is_healthy(provider, model or ""):
                continue
            base_url = self._base_url(provider)
            api_key = self._api_key(provider)
            if base_url is None:
                continue
            if provider != "ollama" and not api_key:
                continue
            resolved_model = model or DEFAULT_MODELS.get(provider, "gpt-4.1-mini")
            try:
                # Run the POST out-of-process so a stalled OpenRouter recv can be SIGKILLed
                # at the OS level (httpx's read timeout + signal.alarm BOTH fail to interrupt
                # a half-open recv on macOS). _llm_post.timed_post bounds every call by
                # wall-clock and raises on stall, feeding the caller's retry/fallback.
                _data, _status = _llm_post.timed_post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    {"Authorization": f"Bearer {api_key}"} if api_key else {},
                    self._payload(provider, resolved_model, messages, temperature, max_tokens),
                    timeout_s=30,
                )
                if _status >= 400:
                    detail = ""
                    if isinstance(_data, dict) and _data.get("error"):
                        detail = f" API error: {_data['error']}"
                    raise RuntimeError(
                        f"{provider}/{resolved_model} returned no completions "
                        f"(status {_status}).{detail}"
                    )
                data = _data
                if not isinstance(data, dict) or not data.get("choices"):
                    detail = ""
                    if isinstance(data, dict) and data.get("error"):
                        detail = f" API error: {data['error']}"
                    raise RuntimeError(
                        f"{provider}/{resolved_model} returned no completions "
                        f"(status {_status}).{detail}"
                    )
                choice = data["choices"][0]["message"]["content"]
                if not choice:
                    # OpenRouter/OpenAI sometimes return null/empty content on a refusal
                    # or filtered response. A None here would later crash len()/json.loads
                    # downstream; treat it as a failed completion so fallback/retry kicks in.
                    raise RuntimeError(
                        f"{provider}/{resolved_model} returned an empty (null) completion."
                    )
                usage = data.get("usage", {})
                # Success on this (provider, model): clear its cooldown counter.
                self._health[(provider, resolved_model)] = _ProviderHealth()
                return CompletionResult(
                    text=choice,
                    provider=provider,
                    model=resolved_model,
                    tokens_in=usage.get("prompt_tokens", 0),
                    tokens_out=usage.get("completion_tokens", 0),
                )
            except Exception as exc:  # noqa: BLE001 - any failure triggers fallback
                last_error = exc
                self._mark_failure(provider, resolved_model)
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def close(self) -> None:
        self._client.close()

    def complete_targeted(
        self,
        provider: "ProviderName",
        model: str,
        messages: list[OpenAIChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        """Complete on one specific provider + model (used by the fusion router)."""
        if provider not in self._order:
            raise RuntimeError(f"Provider not configured: {provider}")
        if not self._is_healthy(provider, model):
            raise RuntimeError(f"Model {provider}/{model} is in cooldown (recent failures).")
        base_url = self._base_url(provider)
        api_key = self._api_key(provider)
        if base_url is None or (provider != "ollama" and not api_key):
            raise RuntimeError(f"Provider unavailable (no base_url/key): {provider}")
        try:
            # Out-of-process POST so a stalled recv is OS-killable (see complete()).
            _data, _status = _llm_post.timed_post(
                f"{base_url.rstrip('/')}/chat/completions",
                {"Authorization": f"Bearer {api_key}"} if api_key else {},
                self._payload(provider, model, messages, temperature, max_tokens),
                timeout_s=30,
            )
            if _status >= 400:
                detail = ""
                if isinstance(_data, dict) and _data.get("error"):
                    detail = f" API error: {_data['error']}"
                raise RuntimeError(
                    f"{provider}/{model} returned no completions (status {_status}).{detail}"
                )
            data = _data
            # OpenRouter/OpenAI return {"error": {...}} (or an empty "choices") on many
            # failure modes (throttle, content filter, model unavailable). Indexing
            # choices[0] blindly crashed the whole editorial run with a cryptic
            # "tuple/list index out of range". Guard it and surface a clear message.
            if not isinstance(data, dict) or not data.get("choices"):
                detail = ""
                if isinstance(data, dict) and data.get("error"):
                    detail = f" API error: {data['error']}"
                raise RuntimeError(
                    f"{provider}/{model} returned no completions (status {resp.status_code}).{detail}"
                )
            choice = data["choices"][0]["message"]["content"]
            if not choice:
                # Null/empty content (refusal / filtered) — treat as a failure so it hits
                # fallback/retry rather than poisoning downstream len()/json.loads.
                raise RuntimeError(
                    f"{provider}/{model} returned an empty (null) completion."
                )
            usage = data.get("usage", {})
            # Success on this (provider, model): clear its cooldown counter.
            self._health[(provider, model)] = _ProviderHealth()
            return CompletionResult(
                text=choice,
                provider=provider,
                model=model,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_failure(provider, model)
            if isinstance(exc, RuntimeError) and "no completions" in str(exc):
                raise  # already a clear message
            raise RuntimeError(f"{provider}/{model} failed: {exc}") from exc
