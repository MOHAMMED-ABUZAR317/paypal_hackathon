"""SQLAlchemy models - the auditable ledger behind RainCheck.

Tables: members, policies, pools, events, decisions, payouts, contributions,
audit_log. Every money movement has a row; nothing is only in memory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import (
    DEFAULT_CONTRIBUTION_MINOR,
    DEFAULT_WAITING_HOURS,
    DEFAULT_MAX_PAYOUTS_PER_MONTH,
    METRIC_PRECIP_24H,
    SCHEMA_VERSION,
    TRIGGER_RAINFALL,
)
from .db import Base


def utcnow() -> datetime:
    """Naive UTC, stored consistently by SQLite and Postgres alike.

    Every internal comparison normalises through ``rules.as_utc``; API responses
    add the ``Z`` suffix explicitly.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pool"))
    name: Mapped[str] = mapped_column(String(120), default="RainCheck Community Pool")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payout_balance_minor: Mapped[int] = mapped_column(Integer, default=0)
    reserve_balance_minor: Mapped[int] = mapped_column(Integer, default=0)
    running_costs_minor: Mapped[int] = mapped_column(Integer, default=0)
    contribution_amount_minor: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_CONTRIBUTION_MINOR
    )
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @property
    def total_balance_minor(self) -> int:
        return self.payout_balance_minor + self.reserve_balance_minor


class Member(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    paypal_email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    zone: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    signup_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    payout_email_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    policies: Mapped[list["Policy"]] = relationship(back_populates="member")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pol"))
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), index=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"), index=True)

    schema_version: Mapped[str] = mapped_column(String(8), default=SCHEMA_VERSION)
    trigger_type: Mapped[str] = mapped_column(String(32), default=TRIGGER_RAINFALL)
    data_source: Mapped[str] = mapped_column(String(32), default="open-meteo")
    zone: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(48), default=METRIC_PRECIP_24H)
    comparator: Mapped[str] = mapped_column(String(4), default=">=")
    threshold: Mapped[float] = mapped_column(Float, default=50.0)
    payout_amount_minor: Mapped[int] = mapped_column(Integer, default=50_000)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    max_payouts_per_day: Mapped[int] = mapped_column(Integer, default=1)
    max_payouts_per_month: Mapped[int] = mapped_column(Integer, default=3)
    waiting_period_hours: Mapped[int] = mapped_column(Integer, default=48)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_source: Mapped[str] = mapped_column(String(16), default="rules")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_flags: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    member: Mapped[Member] = relationship(back_populates="policies")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("pool_id", "event_key", name="uq_event_pool_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt"))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(160), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default=TRIGGER_RAINFALL)
    data_source: Mapped[str] = mapped_column(String(32), default="open-meteo")
    zone: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(48), default=METRIC_PRECIP_24H)
    value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float, default=50.0)
    days: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(16), default="simulated")
    status: Mapped[str] = mapped_column(String(16), default="received")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("event_id", "policy_id", name="uq_decision_event_policy"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dec"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    reason_code: Mapped[str] = mapped_column(String(48), index=True)
    reason_detail: Mapped[str] = mapped_column(Text, default="")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    payable_days: Mapped[int] = mapped_column(Integer, default=0)
    amount_minor: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pay"))
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), unique=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), index=True)

    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    send_currency: Mapped[str] = mapped_column(String(3), default="USD")
    send_amount: Mapped[str] = mapped_column(String(16), default="0.00")

    status: Mapped[str] = mapped_column(String(16), default="CREATED", index=True)
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receiver: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Contribution(Base):
    __tablename__ = "contributions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("con"))
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), index=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(16), default="CREATED")
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    capture_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(32), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
