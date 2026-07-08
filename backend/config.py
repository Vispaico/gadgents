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

    # LLM provider order for fallback routing.
    llm_provider_order: str = "openai,groq,openrouter,ollama"
    openai_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = ""  # e.g. http://localhost:11434/v1

    # Billing
    credit_price_per_usd: int = 100  # 100 credits == $1.00
    free_credits_on_signup: int = 50  # $0.50 free to try
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # App
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()


ProviderName = Literal["openai", "groq", "openrouter", "ollama"]
