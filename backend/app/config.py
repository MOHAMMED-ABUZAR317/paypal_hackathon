"""Application configuration.

Deliberately dependency-free: reads process environment variables, optionally
layered on top of a local ``.env`` file. Secrets never live in the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE, # comments). Never overrides real env."""
    for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, str(default)).lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "RainCheck"))
    env: str = field(default_factory=lambda: _env("ENV", "development"))
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in _env(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        )
    )

    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite:///./data/raincheck.db")
    )
    auto_seed: bool = field(default_factory=lambda: _env_bool("AUTO_SEED", True))
    seed_members: int = field(default_factory=lambda: _env_int("SEED_MEMBERS", 10_000))

    operator_api_key: str = field(
        default_factory=lambda: _env("OPERATOR_API_KEY", "dev-operator-key")
    )

    paypal_mode: str = field(default_factory=lambda: _env("PAYPAL_MODE", "mock").lower())
    paypal_client_id: str = field(default_factory=lambda: _env("PAYPAL_CLIENT_ID"))
    paypal_client_secret: str = field(default_factory=lambda: _env("PAYPAL_CLIENT_SECRET"))
    paypal_api_base: str = field(
        default_factory=lambda: _env("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
    )
    paypal_webhook_id: str = field(default_factory=lambda: _env("PAYPAL_WEBHOOK_ID"))
    paypal_sender_email: str = field(
        default_factory=lambda: _env("PAYPAL_SENDER_EMAIL", "raincheck-sandbox@example.com")
    )
    paypal_payout_currency: str = field(
        default_factory=lambda: _env("PAYPAL_PAYOUT_CURRENCY", "USD").upper()
    )
    payout_inr_per_usd: float = field(
        default_factory=lambda: _env_float("PAYOUT_INR_PER_USD", 83.0)
    )

    ai_base_url: str = field(
        default_factory=lambda: _env("AI_BASE_URL", "https://api.openai.com/v1")
    )
    ai_api_key: str = field(default_factory=lambda: _env("AI_API_KEY"))
    ai_model: str = field(default_factory=lambda: _env("AI_MODEL", "gpt-4o-mini"))
    ai_timeout_seconds: float = field(
        default_factory=lambda: _env_float("AI_TIMEOUT_SECONDS", 20.0)
    )

    open_meteo_base: str = field(
        default_factory=lambda: _env(
            "OPEN_METEO_BASE", "https://api.open-meteo.com/v1/forecast"
        )
    )
    poll_interval_minutes: int = field(
        default_factory=lambda: _env_int("POLL_INTERVAL_MINUTES", 5)
    )
    zapier_webhook_url: str = field(default_factory=lambda: _env("ZAPIER_WEBHOOK_URL"))

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def use_real_paypal(self) -> bool:
        """Real sandbox calls only when explicitly asked AND credentials exist."""
        return self.paypal_mode == "sandbox" and self.paypal_configured

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key)

    def public_config(self) -> dict:
        """Settings that are safe to expose to the browser."""
        return {
            "app_name": self.app_name,
            "env": self.env,
            "paypal": {
                "mode": "sandbox" if self.use_real_paypal else "mock",
                "configured": self.paypal_configured,
                "webhook_configured": bool(self.paypal_webhook_id),
                "payout_currency": self.paypal_payout_currency,
                "inr_per_usd": self.payout_inr_per_usd,
            },
            "ai": {
                "enabled": self.ai_configured,
                "model": self.ai_model if self.ai_configured else "deterministic-fallback",
                "provider": "openai-compatible" if self.ai_configured else "rules",
            },
            "poll_interval_minutes": self.poll_interval_minutes,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
