from __future__ import annotations

"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_valid_fernet_key(key: str) -> bool:
    """True if `key` is a well-formed Fernet key (32-byte url-safe base64)."""
    try:
        import base64

        raw = base64.urlsafe_b64decode(key.encode("utf-8"))
        return len(raw) == 32
    except Exception:
        return False


class Settings(BaseSettings):
    """Central configuration. Secrets must come from env — never hardcode."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://sterling:change_me_strong_password@localhost:5432/sterling",
        alias="DATABASE_URL",
    )
    # When true (or Postgres unreachable), use sqlite:///./data/sterling.db
    force_sqlite: bool = Field(default=False, alias="FORCE_SQLITE")

    jwt_secret_key: str = Field(
        default="dev-only-insecure-secret-change-me-now",
        alias="JWT_SECRET_KEY",
        min_length=16,
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    field_encryption_key: str = Field(default="", alias="FIELD_ENCRYPTION_KEY")

    # Frontend base URL used to build password-reset links
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")

    # SMTP (Gmail) for transactional email — password reset, etc.
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    password_reset_token_ttl_minutes: int = Field(
        default=30, alias="PASSWORD_RESET_TOKEN_TTL_MINUTES"
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )
    environment: str = Field(default="development", alias="ENVIRONMENT")
    testing: bool = Field(default=False, alias="TESTING")
    # When true, rate-limit / client IP uses X-Forwarded-For (only safe behind a
    # trusted reverse proxy such as Render/nginx). Spoofable if left true on a
    # publicly reachable origin that is NOT behind such a proxy.
    trust_proxy: bool = Field(default=False, alias="TRUST_PROXY")
    # If non-empty, POST /auth/signup requires a matching invite_code.
    signup_invite_code: str = Field(default="", alias="SIGNUP_INVITE_CODE")

    # Payment step-up authorization. When True, POST /confirm-payment requires the
    # caller to be an approver/owner AND to present a valid step-up MFA code (TOTP)
    # or a signed payment-provider webhook. Off by default preserves the existing
    # single-operator flow; production deployments should enable it.
    payment_stepup_required: bool = Field(default=False, alias="PAYMENT_STEPUP_REQUIRED")
    # Shared secret the payment provider signs webhooks with (HMAC-SHA256 over the
    # raw body, sent in the X-Payment-Signature header). Empty disables the webhook.
    payment_webhook_secret: str = Field(default="", alias="PAYMENT_WEBHOOK_SECRET")
    # Optional per-operator TOTP secret (base32) for the step-up MFA challenge.
    payment_stepup_totp_secret: str = Field(default="", alias="PAYMENT_STEPUP_TOTP_SECRET")

    # Dual-provider LLM routing
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    # Defaults use widely available model IDs; override via env for newer tiers.
    openai_writer_model: str = Field(default="gpt-4o", alias="OPENAI_WRITER_MODEL")
    openai_execution_model: str = Field(default="gpt-4o", alias="OPENAI_EXECUTION_MODEL")
    openai_execution_model_medium: str = Field(
        default="gpt-4o-mini", alias="OPENAI_EXECUTION_MODEL_MEDIUM"
    )
    anthropic_opus_model: str = Field(default="claude-opus-4-20250514", alias="ANTHROPIC_OPUS_MODEL")
    anthropic_tier2_model: str = Field(
        default="claude-sonnet-4-20250514", alias="ANTHROPIC_TIER2_MODEL"
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com",
        alias="ANTHROPIC_BASE_URL",
    )
    anthropic_scout_model: str = Field(
        default="claude-sonnet-4-20250514", alias="ANTHROPIC_SCOUT_MODEL"
    )

    # Legacy single-key fallback (maps to OpenAI writer if OPENAI_API_KEY unset)
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o", alias="LLM_MODEL")

    # RAG / Chroma
    chroma_persist_dir: str = Field(default="./data/chroma_db", alias="CHROMA_PERSIST_DIR")
    portfolio_collection: str = Field(default="portfolio", alias="PORTFOLIO_COLLECTION")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # Pricing defaults (USD/hr baseline)
    base_hourly_rate: float = Field(default=75.0, alias="BASE_HOURLY_RATE")
    min_bid: float = Field(default=150.0, alias="MIN_BID")
    max_bid: float = Field(default=25000.0, alias="MAX_BID")

    # Alerts (notification only — never auto-send proposals)
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    high_match_threshold: float = Field(default=0.72, alias="HIGH_MATCH_THRESHOLD")
    # Minimum true-cosine match for Scout to admit a lead. Low positive floor:
    # drops only genuinely unrelated (cosine ~0) leads.
    scout_min_match: float = Field(default=0.15, alias="SCOUT_MIN_MATCH")

    # Scout cadence (allowed sources only). Minutes, with jitter.
    scout_interval_min_minutes: int = Field(default=30, alias="SCOUT_INTERVAL_MIN_MINUTES")
    scout_interval_max_minutes: int = Field(default=45, alias="SCOUT_INTERVAL_MAX_MINUTES")
    scout_request_jitter_min_seconds: float = Field(default=2.0, alias="SCOUT_JITTER_MIN_SECONDS")
    scout_request_jitter_max_seconds: float = Field(default=12.0, alias="SCOUT_JITTER_MAX_SECONDS")

    # Optional Redis for distributed idempotency locks
    redis_url: str = Field(default="", alias="REDIS_URL")

    # Sandbox / DinD
    docker_host: str = Field(default="", alias="DOCKER_HOST")
    sandbox_image: str = Field(default="python:3.11-slim", alias="SANDBOX_IMAGE")
    sandbox_node_image: str = Field(default="node:20-slim", alias="SANDBOX_NODE_IMAGE")
    sandbox_rust_image: str = Field(default="rust:1.83-slim", alias="SANDBOX_RUST_IMAGE")
    # Default FALSE: subprocess fallback is NOT a security boundary. Only enable
    # for local/dev when Docker is unavailable and you accept host execution risk.
    sandbox_allow_subprocess_fallback: bool = Field(
        default=False, alias="SANDBOX_ALLOW_SUBPROCESS_FALLBACK"
    )
    captcha_screenshot_dir: str = Field(
        default="./data/captcha_pauses", alias="CAPTCHA_SCREENSHOT_DIR"
    )

    # Residential proxy / Playwright stealth (home country default: Uzbekistan)
    residential_proxy_url: str = Field(default="", alias="RESIDENTIAL_PROXY_URL")
    residential_proxy_username: str = Field(default="", alias="RESIDENTIAL_PROXY_USERNAME")
    residential_proxy_password: str = Field(default="", alias="RESIDENTIAL_PROXY_PASSWORD")
    residential_proxy_country: str = Field(default="UZ", alias="RESIDENTIAL_PROXY_COUNTRY")
    residential_proxy_required: bool = Field(
        default=False, alias="RESIDENTIAL_PROXY_REQUIRED"
    )
    playwright_headed: bool = Field(default=False, alias="PLAYWRIGHT_HEADED")
    playwright_timezone: str = Field(default="Asia/Tashkent", alias="PLAYWRIGHT_TIMEZONE")
    playwright_user_agent: str = Field(default="", alias="PLAYWRIGHT_USER_AGENT")

    # Zero-trust scrubber (always on for Negotiator/QA LLM paths)
    secrets_scrubber_enabled: bool = Field(default=True, alias="SECRETS_SCRUBBER_ENABLED")

    # DLQ worker
    dlq_poll_seconds: float = Field(default=15.0, alias="DLQ_POLL_SECONDS")

    # Follow-up / archive timeouts
    follow_up_after_hours: float = Field(default=48.0, alias="FOLLOW_UP_AFTER_HOURS")
    archive_after_days: float = Field(default=7.0, alias="ARCHIVE_AFTER_DAYS")
    followup_poll_seconds: float = Field(default=3600.0, alias="FOLLOWUP_POLL_SECONDS")

    embedding_model: str = Field(
        default="hashing-384",
        alias="EMBEDDING_MODEL",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        # localhost is a convenience for dev only. In production, appending it to a
        # credentialed allow-list (allow_credentials=True) would let any page on the
        # operator's machine make authenticated cross-origin calls.
        defaults = [] if self.is_production else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
        # A CORS origin must be scheme://host. Managed hosts (Render's
        # `fromService host`) inject a bare hostname; prepend https:// so the
        # browser's "Origin: https://…" header matches the allow-list.
        def _as_origin(value: str) -> str:
            v = value.strip().rstrip("/")
            if not v or "://" in v:
                return v
            return f"https://{v}"

        configured = [
            _as_origin(o) for o in self.cors_origins.split(",") if o.strip()
        ]
        # Dedupe while preserving order
        seen: set[str] = set()
        out: List[str] = []
        for o in configured + defaults:
            if o not in seen:
                seen.add(o)
                out.append(o)
        return out

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def _forbid_insecure_defaults_in_prod(self) -> "Settings":
        """Fail fast if production is left on the shipped dev secrets.

        Otherwise a deploy that forgets JWT_SECRET_KEY silently runs on a public,
        known signing key — anyone could forge valid tokens.
        """
        # If a TOTP secret is configured, step-up is mandatory — a bare session
        # cookie must not release the payment kill-switch.
        if (self.payment_stepup_totp_secret or "").strip():
            object.__setattr__(self, "payment_stepup_required", True)

        if self.testing:
            return self

        if self.is_production:
            offenders = []
            if self.jwt_secret_key == "dev-only-insecure-secret-change-me-now":
                offenders.append("jwt_secret_key")
            if "change_me_strong_password" in self.database_url:
                offenders.append("database_url")
            key = (self.field_encryption_key or "").strip()
            if not key:
                offenders.append("field_encryption_key (missing)")
            elif not _is_valid_fernet_key(key):
                # A malformed key means writes would raise at runtime and sensitive
                # columns could silently fall back to plaintext — lock init instead.
                offenders.append(
                    "field_encryption_key (improperly formatted — must be a 32-byte "
                    "url-safe base64 Fernet key)"
                )
            if offenders:
                raise ValueError(
                    "ENVIRONMENT=production but insecure defaults are still set for: "
                    f"{', '.join(offenders)}. Set real values via environment variables."
                )
        return self

    @property
    def effective_openai_key(self) -> str:
        return self.openai_api_key or self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
