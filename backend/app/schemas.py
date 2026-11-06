"""Pydantic request/response contracts.

The policy object here is the frozen schema (v1.0) shared by the AI parser, the
rule engine, the API and the frontend. Treat it as the public contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .constants import (
    DEFAULT_WAITING_HOURS,
    DEFAULT_ZONE,
    SCHEMA_VERSION,
    SUPPORTED_TRIGGER_TYPES,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Policy schema v1.0 (frozen at the end of checkpoint 1)
# ---------------------------------------------------------------------------


class PolicyPreview(BaseModel):
    """A parsed, validated, bounded policy. Nothing here can move money."""

    schema_version: str = SCHEMA_VERSION
    trigger_type: str = "rainfall"
    data_source: str = "open-meteo"
    zone: str = DEFAULT_ZONE
    metric: str = "precipitation_sum_mm_24h"
    operator: str = ">="
    threshold: float = 50.0
    payout_amount_minor: int = 50_000
    currency: str = "INR"
    max_payouts_per_day: int = 1
    max_payouts_per_month: int = 3
    waiting_period_hours: int = DEFAULT_WAITING_HOURS

    # --- explanation layer (never used by the rule engine) ---
    plain_language: str = ""
    source: Literal["llm", "rules", "edited"] = "rules"
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.7

    @field_validator("trigger_type")
    @classmethod
    def _supported_trigger(cls, value: str) -> str:
        if value not in SUPPORTED_TRIGGER_TYPES:
            raise ValueError(f"Unsupported trigger_type '{value}'")
        return value


class PolicyParseRequest(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    zone: str = DEFAULT_ZONE
    member_id: str | None = None


class PolicyParseResponse(BaseModel):
    ok: bool
    policy: PolicyPreview | None = None
    error: str | None = None
    attempts: int = 1


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


class MemberIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    paypal_email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    zone: str = DEFAULT_ZONE
    device_id: str | None = Field(default=None, max_length=64)
    signup_ip: str | None = Field(default=None, max_length=64)
    verified: bool = True


class EnrollRequest(BaseModel):
    member: MemberIn
    policy: PolicyPreview
    source_text: str | None = Field(default=None, max_length=500)


class EnrollResponse(BaseModel):
    member: dict[str, Any]
    policy: dict[str, Any]
    screening: dict[str, Any]
    receipt: str
    blocked: bool = False


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------


class FundRequest(BaseModel):
    member_id: str
    amount_minor: int | None = Field(default=None, ge=100, le=10_000_000)


class FundResponse(BaseModel):
    contribution_id: str
    order_id: str
    provider: str
    mock: bool
    approve_url: str | None = None
    amount_minor: int
    currency: str
    status: str


class CaptureRequest(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class SimulateEventRequest(BaseModel):
    zone: str = DEFAULT_ZONE
    rainfall_mm: float = Field(default=62.0, ge=0, le=1000)
    days: int = Field(default=1, ge=1, le=3)
    event_key: str | None = Field(default=None, max_length=120)
    trigger_type: str = "rainfall"


class PauseRequest(BaseModel):
    paused: bool
    reason: str | None = Field(default=None, max_length=255)


class RetryRequest(BaseModel):
    event_id: str | None = None
    payout_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Read models (kept loose so the ledger can evolve without breaking the UI)
# ---------------------------------------------------------------------------


class PoolStats(BaseModel):
    pool: dict[str, Any]
    members: dict[str, Any]
    coverage: dict[str, Any]
    performance: dict[str, Any]
    forecast: dict[str, Any]
    guards: dict[str, Any]


class LedgerRow(BaseModel):
    id: str
    created_at: datetime
    member_name: str | None = None
    zone: str | None = None
    event_id: str | None = None
    amount_minor: int = 0
    send_amount: str = "0.00"
    send_currency: str = "USD"
    status: str
    reason_code: str | None = None
    reason_detail: str | None = None
    provider: str = "mock"
    batch_id: str | None = None
    mock: bool = True
