from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
    )

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Database
    database_url: str = "sqlite:///./gadgents.db"

    # LLM provider fallback order: OpenRouter (main catalog + free daily quota) ->
    # NVIDIA NIM (free hosted models, OpenAI-compatible) -> OpenAI (specific high-quality
    # models, free daily quota on Tier 2) -> DeepSeek (cheap direct) -> Ollama (local, free).
    llm_provider_order: str = "openrouter,nvidia,openai,deepseek,ollama"
    openai_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = ""  # e.g. http://localhost:11434/v1

    # OpenAI model ids (overridable via .env). The .env keys carry __<in>__<out> cent
    # price suffixes for cost visibility; the alias maps them to the clean python name.
    # NOTE: openai codex / mini / nano models were removed from .env — see NVIDIA mirrors
    # (nvidia_model_ds4flfree, nvidia_model_nena3) and the coder agent swap below.
    openai_model_sol: str = Field(default="gpt-5.6-sol", alias="OPENAI_MODEL_SOL_250K__5__30")
    openai_model_terra: str = Field(default="gpt-5.6-terra", alias="OPENAI_MODEL_TERRA_2_5M__2_50__15")
    openai_model_luna: str = Field(default="gpt-5.6-luna", alias="OPENAI_MODEL_LUNA_2_5M__1__6")

    # OpenRouter model ids (overridable via .env). .env keys carry __<in>__<out> cent
    # price suffixes; aliases map them to clean python names. Keyed by catalog id (or-<name>).
    openrouter_model_opus: str = Field(default="anthropic/claude-opus-4.8", alias="OPENROUTER_MODEL_OPUS48__5__25")
    openrouter_model_sonnet5: str = Field(default="anthropic/claude-sonnet-5", alias="OPENROUTER_MODEL_SONNET5__2__10")
    openrouter_model_sonnet46: str = Field(default="anthropic/claude-sonnet-4.6", alias="OPENROUTER_MODEL_SONNET46__3__15")
    openrouter_model_kimi: str = Field(default="moonshotai/kimi-k3", alias="OPENROUTER_MODEL_KIMIK3__3__15")
    openrouter_model_ds_pro: str = Field(default="deepseek/deepseek-v4-pro", alias="OPENROUTER_MODEL_DS_PRO__0_45__0_88")
    openrouter_model_nex: str = Field(default="nex-agi/nex-n2-pro", alias="OPENROUTER_MODEL_LAG__0_25__1")
    openrouter_model_qwen37: str = Field(default="qwen/qwen3.7-plus", alias="OPENROUTER_MODEL_QWEN37__0_32__01_28")
    openrouter_model_qwen36: str = Field(default="qwen/qwen3.6-35b-a3b", alias="OPENROUTER_MODEL_QWEN36__0_13__1")
    openrouter_model_qwen35: str = Field(default="qwen/qwen3.5-plus-02-15", alias="OPENROUTER_MODEL_QWEN35__0_26__1_56")
    openrouter_model_glm: str = Field(default="z-ai/glm-5.2", alias="OPENROUTER_MODEL_GLM__0_30__0_95")
    openrouter_model_hy3: str = Field(default="tencent/hy3", alias="OPENROUTER_MODEL_HY3__0_14__0_58")
    openrouter_model_nemotron: str = Field(default="nvidia/nemotron-3-super-120b-a12b", alias="OPENROUTER_MODEL_NESU3__0_08__0_45")
    openrouter_model_mimo: str = Field(default="xiaomi/mimo-v2.5-pro", alias="OPENROUTER_MODEL_MIMO25PRO__0_35__0_70")
    openrouter_model_haiku: str = Field(default="anthropic/claude-haiku-latest", alias="OPENROUTER_MODEL_HAIKU__1__5")
    openrouter_model_llama33: str = Field(default="meta-llama/llama-3.3-70b-instruct", alias="OPENROUTER_MODEL_LLAMA33__0_10__0_32")
    openrouter_model_ds_flash: str = Field(default="deepseek/deepseek-v4-flash", alias="OPENROUTER_MODEL_DS_FLASH__0_09__0_18")
    openrouter_model_ds_flash_free: str = Field(default="deepseek/deepseek-v4-flash:free", alias="OPENROUTER_MODEL_DS_FLASH_FREE")
    openrouter_model_owl: str = "openrouter/owl-alpha"
    # Aion Labs storytelling/narrative models — purpose-fit for the Editorial Creator
    # stage (narrative structure, tension, voice). .env keys: OPENROUTER_MODEL_AION_LABS3
    # (full) and OPENROUTER_MODEL_AION_LABS3_MINI (cheaper, DeepSeek-based).
    openrouter_model_aion_labs3: str = Field(default="aion-labs/aion-3.0", alias="OPENROUTER_MODEL_AION_LABS3__3__6")
    openrouter_model_aion_labs3_mini: str = Field(default="aion-labs/aion-3.0-mini", alias="OPENROUTER_MODEL_AION_LABS3_MINI__0_70__1_40")

    # NVIDIA NIM hosted models (free, OpenAI-compatible). Alias = exact NVIDIA_MODEL_* .env key.
    nvidia_model_ds4flfree: str = Field(default="poolside/laguna-xs-2.1", alias="NVIDIA_MODEL_DS4FLFREE")
    nvidia_model_nena3: str = Field(default="nvidia/nemotron-3-nano-30b-a3b", alias="NVIDIA_MODEL_NENA3")
    nvidia_model_nesu3: str = Field(default="nvidia/nemotron-3-super-120b-a12b", alias="NVIDIA_MODEL_NESU3")
    nvidia_model_neul3: str = Field(default="nvidia/nemotron-3-ultra-550b-a55b", alias="NVIDIA_MODEL_NEUL3")

    # DeepSeek platform models (direct, OpenAI-compatible). Alias = exact DEEPSEEK_MODEL_* .env key.
    deepseek_model_ds4pro: str = Field(default="deepseek-v4-pro", alias="DEEPSEEK_MODEL_DS4PRO__0_44__0_88")
    deepseek_model_ds4flash: str = Field(default="deepseek-v4-flash", alias="DEEPSEEK_MODEL_DS4FLASH__0_14__0_28")

    # Billing
    credit_price_per_usd: int = 100  # 100 credits == $1.00
    free_credits_on_signup: int = 50  # $0.50 free to try
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Error monitoring (Sentry / GlitchTip). Leave blank to skip initialization.
    # Separate DSNs for frontend (React) and backend (FastAPI).
    sentry_frontend_dsn: str = ""
    sentry_backend_dsn: str = ""

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

    # Social Listener (agent #5): CloakBrowser stealth Chromium scraping of X / LinkedIn.
    # Reads its logged-in session from a persistent profile. Optional residential proxy
    # recommended to avoid IP-level bans. CloakBrowser must be `pip install`ed separately.
    cloakbrowser_license_key: str = ""  # Pro builds (v148+) require a subscription
    social_proxy: str = ""               # e.g. http://user:pass@host:port (residential)
    social_profile_dir: str = ""        # persistent profile path holding the logged-in session


@lru_cache
def get_settings() -> Settings:
    return Settings()


def openai_model_ids() -> dict[str, str]:
    """Resolved OpenAI model ids (env-overridable). Keyed by role used in the catalog."""
    s = get_settings()
    return {
        "sol": s.openai_model_sol,
        "terra": s.openai_model_terra,
        "luna": s.openai_model_luna,
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
        "aion3": s.openrouter_model_aion_labs3,
        "aion3_mini": s.openrouter_model_aion_labs3_mini,
    }


def nvidia_model_ids() -> dict[str, str]:
    """Resolved NVIDIA NIM model ids (free hosted, OpenAI-compatible). Keyed by role."""
    s = get_settings()
    return {
        "ds4flfree": s.nvidia_model_ds4flfree,
        "nena3": s.nvidia_model_nena3,
        "nesu3": s.nvidia_model_nesu3,
        "neul3": s.nvidia_model_neul3,
    }


def deepseek_model_ids() -> dict[str, str]:
    """Resolved DeepSeek platform model ids (direct, OpenAI-compatible). Keyed by role."""
    s = get_settings()
    return {
        "ds4pro": s.deepseek_model_ds4pro,
        "ds4flash": s.deepseek_model_ds4flash,
    }


ProviderName = Literal["openai", "groq", "openrouter", "nvidia", "deepseek", "ollama"]
