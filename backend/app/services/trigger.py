"""Trigger engine: normalise public data into events, then run the decision flow.

Order of operations (matches the architecture doc exactly):

1. scheduler fetches data, or the operator injects a demo event
2. the normaliser produces one standard event shape
3. candidate policies are selected by zone + trigger type
4. the screener scores each candidate (advisory only)
5. the rule engine returns APPROVE / DENY / HOLD_FOR_REVIEW with a reason code
6. approvals become PayPal payout rows, spent from the pool as we go
7. one batch per 500 items is sent to PayPal
8. the audit log stores everything
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..constants import (
    DATA_SOURCE_OPEN_METEO,
    EVENT_PROCESSED,
    EVENT_RECEIVED,
    METRIC_PRECIP_24H,
    OUTCOME_APPROVE,
    TRIGGER_RAINFALL,
    ZONES,
)
from ..models import Decision, Event, Member, Payout, Policy, Pool, utcnow
from . import audit, payout_service, screening
from .paypal import get_paypal_client
from .rules import evaluate

# One lock per pool: prevents two simultaneous events double-spending the pool.
_POOL_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _pool_lock(pool_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if pool_id not in _POOL_LOCKS:
            _POOL_LOCKS[pool_id] = threading.Lock()
        return _POOL_LOCKS[pool_id]


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalise_rainfall_event(
    *,
    zone: str,
    value: float,
    days: int = 1,
    mode: str = "simulated",
    event_key: str | None = None,
    data_source: str = DATA_SOURCE_OPEN_METEO,
    raw: dict | None = None,
    threshold: float = 50.0,
) -> dict:
    """One standard event shape, whether it came from Open-Meteo or the demo button."""
    if zone not in ZONES:
        raise ValueError(f"Unknown zone '{zone}'")
    return {
        "trigger_type": TRIGGER_RAINFALL,
        "data_source": data_source,
        "zone": zone,
        "metric": METRIC_PRECIP_24H,
        "value": float(value),
        "threshold": float(threshold),
        "days": max(1, min(3, int(days))),
        "mode": mode,
        "event_key": event_key or f"sim:{zone}:{uuid.uuid4().hex[:10]}",
        "raw": raw or {},
    }


def event_public(event: Event) -> dict:
    return {
        "id": event.id,
        "event_key": event.event_key,
        "trigger_type": event.trigger_type,
        "data_source": event.data_source,
        "zone": event.zone,
        "metric": event.metric,
        "value": event.value,
        "threshold": event.threshold,
        "days": event.days,
        "mode": event.mode,
        "status": event.status,
        "created_at": iso_z(event.created_at),
        "processed_at": iso_z(event.processed_at),
    }


def event_summary(db: Session, event: Event, *, duplicate: bool = False) -> dict:
    counts_rows = (
        db.query(Decision.outcome, func.count(Decision.id))
        .filter(Decision.event_id == event.id)
        .group_by(Decision.outcome)
        .all()
    )
    counts = {"APPROVE": 0, "DENY": 0, "HOLD_FOR_REVIEW": 0}
    counts.update({outcome: count for outcome, count in counts_rows})

    reason_rows = (
        db.query(Decision.reason_code, func.count(Decision.id))
        .filter(Decision.event_id == event.id)
        .group_by(Decision.reason_code)
        .order_by(func.count(Decision.id).desc())
        .all()
    )
    paid = (
        db.query(func.coalesce(func.sum(Payout.amount_minor), 0), func.count(Payout.id))
        .filter(Payout.event_id == event.id)
        .first()
    )
    sample = (
        db.query(Decision, Member, Payout)
        .join(Member, Decision.member_id == Member.id)
        .outerjoin(Payout, Payout.decision_id == Decision.id)
        .filter(Decision.event_id == event.id)
        .order_by(Decision.amount_minor.desc(), Decision.risk_score.desc())
        .limit(12)
        .all()
    )
    batches = (
        db.query(Payout.batch_id, Payout.provider, func.count(Payout.id))
        .filter(Payout.event_id == event.id, Payout.batch_id.isnot(None))
        .group_by(Payout.batch_id, Payout.provider)
        .all()
    )
    return {
        "event": event_public(event),
        "duplicate": duplicate,
        "counts": counts,
        "reasons": [{"code": code, "count": count} for code, count in reason_rows],
        "total_paid_minor": int(paid[0] or 0),
        "payout_rows": int(paid[1] or 0),
        "batches": [
            {"batch_id": batch_id, "provider": provider, "items": count}
            for batch_id, provider, count in batches
        ],
        "decisions_sample": [
            {
                "decision_id": decision.id,
                "member_id": member.id,
                "member_name": member.name,
                "zone": member.zone,
                "outcome": decision.outcome,
                "reason_code": decision.reason_code,
                "reason_detail": decision.reason_detail,
                "risk_score": decision.risk_score,
                "payable_days": decision.payable_days,
                "amount_minor": decision.amount_minor,
                "payout_status": payout.status if payout else None,
                "mock": (payout.provider == "mock") if payout else None,
            }
            for decision, member, payout in sample
        ],
    }


async def ingest_event(db: Session, pool: Pool, payload: dict, *, actor: str = "system") -> dict:
    """Insert an event (idempotently) and process it."""
    event_key = payload["event_key"]
    existing = (
        db.query(Event).filter(Event.pool_id == pool.id, Event.event_key == event_key).first()
    )
    if existing:
        audit.log(
            db,
            "event.duplicate_ignored",
            actor=actor,
            entity_type="event",
            entity_id=existing.id,
            detail={"event_key": event_key, "note": "same event_key replayed; no second payout"},
        )
        db.commit()
        return event_summary(db, existing, duplicate=True)

    event = Event(
        pool_id=pool.id,
        event_key=event_key,
        trigger_type=payload["trigger_type"],
        data_source=payload["data_source"],
        zone=payload["zone"],
        metric=payload["metric"],
        value=payload["value"],
        threshold=payload["threshold"],
        days=payload["days"],
        mode=payload["mode"],
        status=EVENT_RECEIVED,
        raw_json=json.dumps(payload.get("raw") or {}, default=str),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Event)
            .filter(Event.pool_id == pool.id, Event.event_key == event_key)
            .first()
        )
        return event_summary(db, existing, duplicate=True)

    audit.log(
        db,
        "event.received",
        actor=actor,
        entity_type="event",
        entity_id=event.id,
        detail={
            "zone": event.zone,
            "value_mm": event.value,
            "days": event.days,
            "mode": event.mode,
            "data_source": event.data_source,
        },
    )
    return await process_event(db, pool, event, actor=actor)


async def process_event(db: Session, pool: Pool, event: Event, *, actor: str = "system") -> dict:
    """Run the full decision + payout flow for one event. Idempotent per event."""
    started = time.perf_counter()
    lock = _pool_lock(pool.id)
    if not lock.acquire(timeout=30):
        raise RuntimeError("Another event is being processed for this pool; try again.")
    try:
        db.refresh(pool)
        db.refresh(event)

        if event.status == EVENT_PROCESSED:
            return event_summary(db, event, duplicate=True)

        now = utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        usage_rows = (
            db.query(
                Decision.policy_id,
                func.coalesce(func.sum(Decision.payable_days), 0),
                func.count(Decision.id),
            )
            .join(Policy, Decision.policy_id == Policy.id)
            .filter(
                Policy.pool_id == pool.id,
                Decision.outcome == OUTCOME_APPROVE,
                Decision.created_at >= month_start,
            )
            .group_by(Decision.policy_id)
            .all()
        )
        days_used = {policy_id: int(days or 0) for policy_id, days, _ in usage_rows}
        payouts_month = {policy_id: int(count) for policy_id, _, count in usage_rows}

        today_rows = (
            db.query(Decision.policy_id, func.count(Decision.id))
            .join(Policy, Decision.policy_id == Policy.id)
            .filter(
                Policy.pool_id == pool.id,
                Decision.outcome == OUTCOME_APPROVE,
                Decision.created_at >= today_start,
            )
            .group_by(Decision.policy_id)
            .all()
        )
        payouts_today = {policy_id: int(count) for policy_id, count in today_rows}

        candidates = (
            db.query(Policy, Member)
            .join(Member, Policy.member_id == Member.id)
            .options(joinedload(Policy.member))
            .filter(
                Policy.pool_id == pool.id,
                Policy.zone == event.zone,
                Policy.trigger_type == event.trigger_type,
                Policy.active.is_(True),
            )
            .order_by(Policy.created_at.asc())
            .all()
        )
        member_screens = screening.bulk_screen(db, [member for _, member in candidates])

        created_payouts: list[Payout] = []
        counts = {"APPROVE": 0, "DENY": 0, "HOLD_FOR_REVIEW": 0}
        reasons: dict[str, int] = {}

        for policy, member in candidates:
            screen = member_screens.get(member.id, screening.ScreenResult(0))
            result = evaluate(
                policy=policy,
                member=member,
                event=event,
                pool=pool,
                risk_score=screen.score,
                days_used_this_month=days_used.get(policy.id, 0),
                payouts_today=payouts_today.get(policy.id, 0),
                now=now,
            )

            decision = Decision(
                event_id=event.id,
                policy_id=policy.id,
                member_id=member.id,
                outcome=result.outcome,
                reason_code=result.reason_code,
                reason_detail=result.reason_detail,
                risk_score=screen.score,
                payable_days=result.payable_days,
                amount_minor=result.amount_minor,
                idempotency_key=f"decision:{event.id}:{policy.id}",
            )
            db.add(decision)
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
            reasons[result.reason_code] = reasons.get(result.reason_code, 0) + 1

            if result.outcome == OUTCOME_APPROVE:
                # Spend immediately so concurrent approvals cannot overdraw the pool.
                payout_service.spend_from_pool(pool, result.amount_minor)
                db.flush()  # assigns decision.id for the payout FK
                payout = payout_service.build_payout(
                    decision=decision,
                    policy=policy,
                    event=event,
                    receiver=member.paypal_email,
                )
                db.add(payout)
                created_payouts.append(payout)
                days_used[policy.id] = days_used.get(policy.id, 0) + result.payable_days
                payouts_today[policy.id] = payouts_today.get(policy.id, 0) + 1

        event.status = EVENT_PROCESSED
        event.processed_at = utcnow()
        db.flush()

        batch_result = await payout_service.send_payouts(
            db, event=event, payouts=created_payouts, actor=actor
        )

        duration_ms = int((time.perf_counter() - started) * 1000)
        audit.log(
            db,
            "event.processed",
            actor=actor,
            entity_type="event",
            entity_id=event.id,
            detail={
                "counts": counts,
                "total_paid_minor": sum(p.amount_minor for p in created_payouts),
                "duration_ms": duration_ms,
                "provider": batch_result.get("provider"),
                "mock": batch_result.get("mock"),
            },
        )
        db.commit()

        summary = event_summary(db, event)
        summary["counts"] = counts
        summary["reasons"] = [
            {"code": code, "count": count}
            for code, count in sorted(reasons.items(), key=lambda kv: -kv[1])
        ]
        summary["duration_ms"] = duration_ms
        summary["payout_result"] = batch_result
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        lock.release()


def last_event_key(db: Session, pool: Pool) -> str | None:
    event = (
        db.query(Event)
        .filter(Event.pool_id == pool.id)
        .order_by(Event.created_at.desc())
        .first()
    )
    return event.event_key if event else None
