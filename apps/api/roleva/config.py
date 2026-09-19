"""Application settings, loaded from environment.

Free-tier limits live here because they are operational facts that change
independently of code: Gemini's RPM/RPD, the per-analysis call budget, and the
per-user quota all need tuning without a redeploy of logic.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    environment: str = "development"
    log_level: str = "INFO"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"

    # --- supabase ---
    supabase_url: str = ""
    # Public by design: it appears in browser code. RLS is what protects the
    # data, which is why the schema migration matters more than this key does.
    supabase_anon_key: str = ""
    # Bypasses RLS entirely. Used only for operational tables that have no
    # policies; user-owned rows are always written with the caller's own token.
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # --- gemini ---
    # Versions are pinned deliberately. The `-latest` aliases would let Google
    # swap the model under us, and Roleva promises that the same resume and job
    # description always produce the same scores.
    gemini_api_key: str = ""
    gemini_model_main: str = "gemini-3.6-flash"
    gemini_model_light: str = "gemini-3.5-flash-lite"
    # Free-tier capacity is shared, and a popular model can be unavailable for
    # minutes at a time. A second model of comparable capability keeps an
    # analysis working rather than failing on someone else's traffic spike.
    gemini_model_fallback: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-2"

    # --- free-tier guardrails ---
    llm_max_rpm: int = Field(default=10, ge=1)
    llm_max_rpd: int = Field(default=250, ge=1)
    llm_max_calls_per_analysis: int = Field(default=6, ge=1)
    llm_timeout_seconds: float = Field(default=25.0, gt=0)

    # --- quotas ---
    user_daily_analysis_quota: int = Field(default=5, ge=1)
    ip_hourly_analysis_quota: int = Field(default=20, ge=1)

    # --- upload limits ---
    max_upload_bytes: int = 8 * 1024 * 1024
    max_pages: int = 10
    min_jd_chars: int = 200
    warn_jd_chars: int = 600
    # Scanned-PDF detection needs two signals, not one. A sparse student resume
    # can legitimately hold under 150 characters on a page, so a text-density
    # threshold alone rejects real documents. The rule is: near-zero text AND a
    # page-covering image. This value is only the first half of that test.
    min_chars_per_page: int = 25

    # --- observability ---
    sentry_dsn: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
