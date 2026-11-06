"""JSON serialisers shared by the routers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .constants import format_inr
from .models import Contribution, Decision, Member, Payout, Policy


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def member_public(member: Member) -> dict:
    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "paypal_email": member.paypal_email,
        "zone": member.zone,
        "verified": member.verified,
        "status": member.status,
        "created_at": iso_z(member.created_at),
    }


def policy_public(policy: Policy) -> dict:
    try:
        flags = json.loads(policy.risk_flags or "[]")
    except ValueError:
        flags = []
    return {
        "id": policy.id,
        "member_id": policy.member_id,
        "schema_version": policy.schema_version,
        "trigger_type": policy.trigger_type,
        "data_source": policy.data_source,
        "zone": policy.zone,
        "metric": policy.metric,
        "operator": policy.comparator,
        "threshold": policy.threshold,
        "payout_amount_minor": policy.payout_amount_minor,
        "payout_display": format_inr(policy.payout_amount_minor),
        "currency": policy.currency,
        "max_payouts_per_day": policy.max_payouts_per_day,
        "max_payouts_per_month": policy.max_payouts_per_month,
        "waiting_period_hours": policy.waiting_period_hours,
        "active": policy.active,
        "starts_at": iso_z(policy.starts_at),
        "ends_at": iso_z(policy.ends_at),
        "source_text": policy.source_text,
        "parser_source": policy.parser_source,
        "risk_score": policy.risk_score,
        "risk_flags": flags,
        "created_at": iso_z(policy.created_at),
    }


def contribution_public(row: Contribution) -> dict:
    return {
        "id": row.id,
        "member_id": row.member_id,
        "amount_minor": row.amount_minor,
        "amount_display": format_inr(row.amount_minor),
        "currency": row.currency,
        "status": row.status,
        "provider": row.provider,
        "order_id": row.order_id,
        "capture_id": row.capture_id,
        "mock": row.provider == "mock",
        "created_at": iso_z(row.created_at),
    }


def decision_public(decision: Decision, member: Member | None = None) -> dict:
    return {
        "id": decision.id,
        "event_id": decision.event_id,
        "policy_id": decision.policy_id,
        "member_id": decision.member_id,
        "member_name": member.name if member else None,
        "outcome": decision.outcome,
        "reason_code": decision.reason_code,
        "reason_detail": decision.reason_detail,
        "risk_score": decision.risk_score,
        "payable_days": decision.payable_days,
        "amount_minor": decision.amount_minor,
        "amount_display": format_inr(decision.amount_minor),
        "created_at": iso_z(decision.created_at),
    }


def payout_public(
    payout: Payout,
    *,
    member: Member | None = None,
    event=None,
    reason_code: str | None = None,
) -> dict:
    return {
        "id": payout.id,
        "created_at": iso_z(payout.created_at),
        "updated_at": iso_z(payout.updated_at),
        "event_id": payout.event_id,
        "zone": event.zone if event else (member.zone if member else None),
        "rainfall_mm": event.value if event else None,
        "member_id": payout.member_id,
        "member_name": member.name if member else None,
        "amount_minor": payout.amount_minor,
        "amount_display": format_inr(payout.amount_minor),
        "send_amount": payout.send_amount,
        "send_currency": payout.send_currency,
        "status": payout.status,
        "reason_code": reason_code,
        "provider": payout.provider,
        "batch_id": payout.batch_id,
        "item_id": payout.item_id,
        "receiver": payout.receiver,
        "failure_reason": payout.failure_reason,
        "mock": payout.provider == "mock",
    }
