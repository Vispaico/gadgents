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

OpenAIChatMessage = dict  # {"role": "system"|"user"|"assistant", "content": str}


@dataclass
class _ProviderHealth:
    failures: int = 0
    cooldown_until: float = 0.0


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
        self._health: dict[ProviderName, _ProviderHealth] = {
            p: _ProviderHealth() for p in self._order
        }
        self._client = httpx.Client(timeout=60.0)

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

    def _is_healthy(self, provider: ProviderName) -> bool:
        h = self._health[provider]
        if h.cooldown_until and time.time() < h.cooldown_until:
            return False
        return True

    def _mark_failure(self, provider: ProviderName) -> None:
        h = self._health[provider]
        h.failures += 1
        if h.failures >= 2:
            h.cooldown_until = time.time() + 30  # 30s cooldown

    def complete(
        self,
        messages: list[OpenAIChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        last_error: Optional[Exception] = None
        for provider in self._order:
            if not self._is_healthy(provider):
                continue
            base_url = self._base_url(provider)
            api_key = self._api_key(provider)
            if base_url is None:
                continue
            if provider != "ollama" and not api_key:
                continue
            resolved_model = model or DEFAULT_MODELS.get(provider, "gpt-4.1-mini")
            try:
                resp = self._client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    json={
                        "model": resolved_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                self._health[provider].failures = 0
                return CompletionResult(
                    text=choice,
                    provider=provider,
                    model=resolved_model,
                    tokens_in=usage.get("prompt_tokens", 0),
                    tokens_out=usage.get("completion_tokens", 0),
                )
            except Exception as exc:  # noqa: BLE001 - any failure triggers fallback
                last_error = exc
                self._mark_failure(provider)
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
        if not self._is_healthy(provider):
            raise RuntimeError(f"Provider unhealthy (cooldown): {provider}")
        base_url = self._base_url(provider)
        api_key = self._api_key(provider)
        if base_url is None or (provider != "ollama" and not api_key):
            raise RuntimeError(f"Provider unavailable (no base_url/key): {provider}")
        try:
            resp = self._client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            self._health[provider].failures = 0
            return CompletionResult(
                text=choice,
                provider=provider,
                model=model,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_failure(provider)
            raise RuntimeError(f"{provider}/{model} failed: {exc}") from exc
