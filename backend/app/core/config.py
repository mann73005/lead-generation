"""Application settings, loaded once from the environment."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    # --- Database ---
    database_url: str

    # --- Auth ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bootstrap_user_email: str = "demo@stylesense.ai"
    bootstrap_user_password: str = "demo1234"

    # --- LLM ---
    gemini_api_key: str = ""
    #: The free tier allows 20 requests per day *per model*, so the fallback
    #: chain is a quota pool as much as an availability measure: each entry
    #: carries its own allowance. The provider walks down it on 429 and 503.
    llm_model: str = "gemini-3.8-flash"
    llm_fallback_models: str = (
        "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3-flash-preview,"
        "gemini-3.1-flash-lite,gemini-3.5-flash"
    )
    llm_timeout_seconds: int = 120

    # Discovery budgets, source rules, seed queries and prompts live in
    # config/discovery.yaml; product identity and the outreach template in
    # config/product.yaml. They are deliberately not duplicated here — two
    # places to set one value is how they end up disagreeing.

    # --- Search / fetch ---
    tavily_api_key: str = ""

    # --- Email ---
    resend_api_key: str = ""
    email_from_name: str = "StyleSense AI"
    email_from_address: str = "onboarding@resend.dev"
    email_override_to: str = ""

    # --- Tracking ---
    public_base_url: str = "http://localhost:8000"

    # --- Scoring ---
    scoring_config_path: Path = Field(default=BACKEND_DIR / "config" / "scoring.yaml")

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: str) -> str:
        """Normalise bare `postgresql://` URLs onto the psycopg 3 driver.

        Supabase hands out `postgresql://...`, which SQLAlchemy resolves to
        psycopg2. We only ship psycopg 3, so rewrite it rather than making
        every developer remember the suffix.
        """
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _derive_public_base_url(self) -> "Settings":
        """Fall back to the hosting platform's own domain variable.

        The tracking pixel's URL has to be whatever the world can reach this
        service at. Hard-coding it means every redeploy to a new domain
        silently breaks open tracking, so the platform is asked first and
        PUBLIC_BASE_URL is only needed to override.
        """
        if self.public_base_url not in ("", "http://localhost:8000"):
            return self

        for variable in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME", "FLY_APP_HOSTNAME"):
            host = os.environ.get(variable)
            if host:
                object.__setattr__(self, "public_base_url", f"https://{host.rstrip('/')}")
                return self

        external = os.environ.get("RENDER_EXTERNAL_URL")
        if external:
            object.__setattr__(self, "public_base_url", external.rstrip("/"))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def llm_model_chain(self) -> list[str]:
        """Primary model first, then fallbacks, de-duplicated."""
        chain = [self.llm_model, *self.llm_fallback_models.split(",")]
        seen: list[str] = []
        for model in (m.strip() for m in chain):
            if model and model not in seen:
                seen.append(model)
        return seen

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def search_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
