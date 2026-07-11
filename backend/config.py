from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Database
    database_url: str = "sqlite:///./gadgents.db"

    # LLM provider fallback order: OpenRouter (main catalog + free daily quota) ->
    # OpenAI (specific high-quality models, free daily quota on Tier 2) -> Ollama (local, free).
    llm_provider_order: str = "openrouter,openai,ollama"
    openai_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = ""  # e.g. http://localhost:11434/v1

    # OpenAI model ids (overridable via .env so you can paste exact names from the
    # OpenAI model page instead of the docs). Defaults are docs-based placeholders.
    openai_model_sol: str = "gpt-5.6-sol"
    openai_model_terra: str = "gpt-5.6-terra"
    openai_model_codex: str = "gpt-5.1-codex"
    openai_model_luna: str = "gpt-5.6-luna"
    openai_model_mini: str = "gpt-5.4-mini-2026-03-17"
    openai_model_nano: str = "gpt-5.4-nano-2026-03-17"

    # OpenRouter model ids (overridable via .env). Lets you swap to limited-time free
    # models or newer slugs without code edits. Keyed by catalog id (or-<name>).
    openrouter_model_opus: str = "anthropic/claude-opus-4.8"
    openrouter_model_sonnet5: str = "anthropic/claude-sonnet-5"
    openrouter_model_sonnet46: str = "anthropic/claude-sonnet-4.6"
    openrouter_model_kimi: str = "moonshotai/kimi-k2.6"
    openrouter_model_ds_pro: str = "deepseek/deepseek-v4-pro"
    openrouter_model_nex: str = "nex-agi/nex-n2-pro"
    openrouter_model_qwen37: str = "qwen/qwen3.7-plus"
    openrouter_model_qwen36: str = "qwen/qwen3.6-35b-a3b"
    openrouter_model_qwen35: str = "qwen/qwen3.5-plus-20260420"
    openrouter_model_glm: str = "z-ai/glm-5.2"
    openrouter_model_hy3: str = "tencent/hy3"
    openrouter_model_nemotron: str = "nvidia/nemotron-3-super-120b-a12b"
    openrouter_model_mimo: str = "xiaomi/mimo-v2-pro"
    openrouter_model_haiku: str = "anthropic/claude-haiku-4.5"
    openrouter_model_llama33: str = "meta-llama/llama-3.3-70b-instruct"
    openrouter_model_ds_flash: str = "deepseek/deepseek-v4-flash"
    openrouter_model_ds_flash_free: str = "deepseek/deepseek-v4-flash:free"
    openrouter_model_owl: str = "openrouter/owl-alpha"

    # Billing
    credit_price_per_usd: int = 100  # 100 credits == $1.00
    free_credits_on_signup: int = 50  # $0.50 free to try
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # App
    cors_origins: str = "http://localhost:5173"

    # Dev / preview mode. When require_login and enable_paywall are both False you can
    # use every agent without an account and without spending credits (good for QA).
    require_login: bool = True
    enable_paywall: bool = True

    # Lead Finder agent: local Firecrawl (firecrawl-simple / firecrawl) base URL + key.
    # Self-hosted, billing-free. The agent only calls Firecrawl when use_firecrawl=True.
    firecrawl_base_url: str = "http://localhost:3002"
    firecrawl_api_key: str = "test-key-123"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def openai_model_ids() -> dict[str, str]:
    """Resolved OpenAI model ids (env-overridable). Keyed by role used in the catalog."""
    s = get_settings()
    return {
        "sol": s.openai_model_sol,
        "terra": s.openai_model_terra,
        "codex": s.openai_model_codex,
        "luna": s.openai_model_luna,
        "mini": s.openai_model_mini,
        "nano": s.openai_model_nano,
    }


def openrouter_model_ids() -> dict[str, str]:
    """Resolved OpenRouter model ids (env-overridable). Keyed by catalog id suffix."""
    s = get_settings()
    return {
        "opus": s.openrouter_model_opus,
        "sonnet5": s.openrouter_model_sonnet5,
        "sonnet46": s.openrouter_model_sonnet46,
        "kimi": s.openrouter_model_kimi,
        "ds_pro": s.openrouter_model_ds_pro,
        "nex": s.openrouter_model_nex,
        "qwen37": s.openrouter_model_qwen37,
        "qwen36": s.openrouter_model_qwen36,
        "qwen35": s.openrouter_model_qwen35,
        "glm": s.openrouter_model_glm,
        "hy3": s.openrouter_model_hy3,
        "nemotron": s.openrouter_model_nemotron,
        "mimo": s.openrouter_model_mimo,
        "haiku": s.openrouter_model_haiku,
        "llama33": s.openrouter_model_llama33,
        "ds_flash": s.openrouter_model_ds_flash,
        "ds_flash_free": s.openrouter_model_ds_flash_free,
        "owl": s.openrouter_model_owl,
    }


ProviderName = Literal["openai", "groq", "openrouter", "ollama"]
