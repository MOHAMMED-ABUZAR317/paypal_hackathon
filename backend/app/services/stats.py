"""Dashboard aggregates: balances, members, coverage and measured performance."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import (
    MAX_PAYOUTS_PER_DAY,
    MAX_PAYOUTS_PER_MONTH,
    PAYOUT_FAILED,
    PAYOUT_SUCCESS,
    format_inr,
)
from ..models import Contribution, Decision, Event, Member, Payout, Policy, Pool
from .forecast import pool_forecast


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pool_public(pool: Pool) -> dict:
    return {
        "id": pool.id,
        "name": pool.name,
        "currency": pool.currency,
        "payout_balance_minor": pool.payout_balance_minor,
        "reserve_balance_minor": pool.reserve_balance_minor,
        "total_balance_minor": pool.total_balance_minor,
        "running_costs_minor": pool.running_costs_minor,
        "contribution_amount_minor": pool.contribution_amount_minor,
        "paused": pool.paused,
        "pause_reason": pool.pause_reason,
        "display": {
            "payout_box": format_inr(pool.payout_balance_minor),
            "reserve_box": format_inr(pool.reserve_balance_minor),
            "total": format_inr(pool.total_balance_minor),
            "contribution": format_inr(pool.contribution_amount_minor),
        },
        "updated_at": _iso(pool.updated_at),
    }


def pool_stats(db: Session, pool: Pool) -> dict:
    settings = get_settings()

    members_total = db.query(func.count(Member.id)).scalar() or 0
    members_active = (
        db.query(func.count(Member.id)).filter(Member.status == "active").scalar() or 0
    )
    members_verified = (
        db.query(func.count(Member.id)).filter(Member.verified.is_(True)).scalar() or 0
    )
    members_blocked = (
        db.query(func.count(Member.id)).filter(Member.status == "blocked").scalar() or 0
    )
    policies_active = (
        db.query(func.count(Policy.id))
        .filter(Policy.pool_id == pool.id, Policy.active.is_(True))
        .scalar()
        or 0
    )
    zone_rows = (
        db.query(Policy.zone, func.count(Policy.id))
        .filter(Policy.pool_id == pool.id)
        .group_by(Policy.zone)
        .order_by(func.count(Policy.id).desc())
        .all()
    )

    paid_rows = (
        db.query(func.count(Payout.id), func.coalesce(func.sum(Payout.amount_minor), 0))
        .filter(Payout.status == PAYOUT_SUCCESS)
        .first()
    )
    failed_rows = (
        db.query(func.count(Payout.id)).filter(Payout.status == PAYOUT_FAILED).scalar() or 0
    )
    held_rows = (
        db.query(func.count(Decision.id))
        .filter(Decision.outcome == "HOLD_FOR_REVIEW")
        .scalar()
        or 0
    )
    events_count = db.query(func.count(Event.id)).filter(Event.pool_id == pool.id).scalar() or 0

    recent = (
        db.query(Payout.created_at, Event.created_at)
        .join(Event, Payout.event_id == Event.id)
        .filter(Payout.status == PAYOUT_SUCCESS)
        .order_by(Payout.created_at.desc())
        .limit(1000)
        .all()
    )
    durations = sorted(
        max(0.0, (payout_at - event_at).total_seconds())
        for payout_at, event_at in recent
        if payout_at and event_at
    )
    avg_seconds = round(sum(durations) / len(durations), 2) if durations else None
    p95_seconds = round(durations[int(len(durations) * 0.95) - 1], 2) if durations else None

    contributions = (
        db.query(func.count(Contribution.id), func.coalesce(func.sum(Contribution.amount_minor), 0))
        .filter(Contribution.status == "COMPLETED")
        .first()
    )

    forecast = pool_forecast(db, pool)
    last_event = (
        db.query(Event)
        .filter(Event.pool_id == pool.id)
        .order_by(Event.created_at.desc())
        .first()
    )

    return {
        "pool": pool_public(pool),
        "members": {
            "total": members_total,
            "active": members_active,
            "verified": members_verified,
            "blocked": members_blocked,
            "policies_active": policies_active,
            "zones": [{"zone": zone, "members": count} for zone, count in zone_rows],
        },
        "coverage": {
            "total_balance_minor": pool.total_balance_minor,
            "payout_box_minor": pool.payout_balance_minor,
            "reserve_box_minor": pool.reserve_balance_minor,
            "expected_event_cost_minor": forecast["expected_event_cost_minor"],
            "assumed_affected_members": forecast["assumed_affected_members"],
            "stress_fraction": forecast["stress_fraction"],
            "events_covered": forecast["events_covered"],
            "storm_days_covered": forecast["events_covered"],
            "member_payouts_covered": round(
                pool.total_balance_minor
                / max(1, forecast["expected_payout_per_member_minor"])
            ),
            "display": {
                "total": format_inr(pool.total_balance_minor),
                "expected_event_cost": format_inr(forecast["expected_event_cost_minor"]),
            },
        },
        "performance": {
            "payouts_success": int(paid_rows[0] or 0),
            "total_paid_minor": int(paid_rows[1] or 0),
            "total_paid_display": format_inr(int(paid_rows[1] or 0)),
            "payouts_failed": int(failed_rows),
            "decisions_held": int(held_rows),
            "events_processed": int(events_count),
            "avg_seconds_trigger_to_payout": avg_seconds,
            "p95_seconds_trigger_to_payout": p95_seconds,
            "last_event_at": _iso(last_event.created_at) if last_event else None,
            "contributions_count": int(contributions[0] or 0),
            "contributions_minor": int(contributions[1] or 0),
        },
        "forecast": forecast,
        "guards": {
            "paused": pool.paused,
            "pause_reason": pool.pause_reason,
            "max_payouts_per_day": MAX_PAYOUTS_PER_DAY,
            "max_payouts_per_month": MAX_PAYOUTS_PER_MONTH,
            "idempotency": "event+policy -> unique key, replay-safe",
            "webhook_signature": "verified before any state change",
            "ai_moves_money": False,
            "provider": "paypal" if settings.use_real_paypal else "mock",
            "provider_label": (
                "PayPal sandbox"
                if settings.use_real_paypal
                else "MOCK payout transport (not real money)"
            ),
            "mock": not settings.use_real_paypal,
        },
    }
