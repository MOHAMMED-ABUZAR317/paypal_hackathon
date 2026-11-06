"""Operator console: pause switch, payout retries, reconciliation, demo tools.

Every action is authenticated, audit-logged and reversible. The demo tools are
labelled as demo tools in the UI and in the audit trail.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import PAYOUT_FAILED, PAYOUT_PENDING, format_inr
from ..db import get_db
from ..models import Event, Member, Payout, Policy, utcnow
from ..repository import require_pool
from ..schemas import PauseRequest, RetryRequest
from ..security import require_operator
from ..serializers import member_public
from ..services import audit, receipts, screening
from ..services.paypal import PayPalError, get_paypal_client
from ..services.payout_service import reconcile_batch, retry_payouts
from ..services.stats import pool_public
from ..seed import RING_PAYOUT_EMAIL, reset_demo

router = APIRouter(tags=["operator"])


@router.post("/operator/pause")
def set_pause(
    payload: PauseRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    pool = require_pool(db)
    pool.paused = payload.paused
    pool.pause_reason = payload.reason if payload.paused else None
    pool.updated_at = utcnow()
    audit.log(
        db,
        "operator.pause" if payload.paused else "operator.resume",
        actor="operator",
        entity_type="pool",
        entity_id=pool.id,
        detail={"paused": payload.paused, "reason": payload.reason},
    )
    db.commit()
    return {
        "pool": pool_public(pool),
        "message": (
            "All payouts are paused. New events will be denied with POOL_PAUSED."
            if payload.paused
            else "Payouts resumed."
        ),
    }


@router.post("/operator/payouts/retry")
async def retry_failed_payouts(
    payload: RetryRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    query = db.query(Payout).filter(Payout.status == PAYOUT_FAILED)
    if payload.event_id:
        query = query.filter(Payout.event_id == payload.event_id)
    if payload.payout_ids:
        query = query.filter(Payout.id.in_(payload.payout_ids))
    failed = query.limit(2000).all()
    if not failed:
        return {"retried": 0, "message": "No failed payouts to retry."}

    by_event: dict[str, list[Payout]] = {}
    for payout in failed:
        by_event.setdefault(payout.event_id, []).append(payout)

    results = []
    for event_id, rows in by_event.items():
        event = db.query(Event).filter(Event.id == event_id).first()
        if event is None:
            continue
        results.append(
            {
                "event_id": event_id,
                **await retry_payouts(db, event=event, payouts=rows),
            }
        )
    db.commit()
    return {"retried": len(failed), "results": results}


@router.post("/operator/payouts/reconcile")
async def reconcile_payouts(
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    """Ask PayPal for the authoritative batch status for every PENDING batch."""
    client = get_paypal_client()
    batches = (
        db.query(Payout.batch_id)
        .filter(Payout.status == PAYOUT_PENDING, Payout.batch_id.isnot(None))
        .distinct()
        .limit(200)
        .all()
    )
    results = []
    for (batch_id,) in batches:
        try:
            payload = await client.get_payout_batch(batch_id)
        except PayPalError as exc:
            results.append({"batch_id": batch_id, "error": str(exc)[:200]})
            continue
        status = (payload.get("batch_header") or {}).get("batch_status", "PENDING")
        updated = reconcile_batch(db, batch_id, status)
        results.append({"batch_id": batch_id, "status": status, "rows_updated": updated})
    db.commit()
    return {"batches_checked": len(results), "results": results}


@router.post("/operator/demo/reset")
def reset(
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    """Rehearsal tool: clear events/payouts, keep members, restore balances."""
    return reset_demo(db, keep_members=True)


@router.post("/operator/demo/fraud-attempt")
def fraud_attempt(
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    """Deliberately try to enroll a sybil account sharing the ring's payout address.

    Demonstrates the block on screen: the rules refuse before any money can move.
    """
    settings = get_settings()
    pool = require_pool(db)
    suffix = uuid.uuid4().hex[:8]
    screen = screening.screen_member(
        db,
        member_id=None,
        paypal_email=RING_PAYOUT_EMAIL,
        device_id="DEV-RING-01",
        signup_ip="203.0.113.7",
        zone="hyderabad-central",
        verified=True,
    )
    blocked = screen.recommendation == "block"

    member = Member(
        name=f"Fraud Demo {suffix}",
        email=f"fraud.demo.{suffix}@example.com",
        paypal_email=RING_PAYOUT_EMAIL,
        zone="hyderabad-central",
        device_id="DEV-RING-01",
        signup_ip="203.0.113.7",
        verified=True,
        status="blocked" if blocked else "active",
        created_at=utcnow(),
    )
    db.add(member)
    db.flush()
    db.add(
        Policy(
            member_id=member.id,
            pool_id=pool.id,
            zone="hyderabad-central",
            threshold=50.0,
            payout_amount_minor=50_000,
            active=not blocked,
            starts_at=utcnow(),
            source_text="Demo: attempt to reuse a payout address",
            parser_source="demo",
            risk_score=screen.score,
            risk_flags=json.dumps([f.code for f in screen.flags]),
        )
    )
    audit.log(
        db,
        "demo.fraud_attempt",
        actor="operator",
        entity_type="member",
        entity_id=member.id,
        detail={
            "blocked": blocked,
            "score": screen.score,
            "flags": [f.code for f in screen.flags],
            "mock": not settings.use_real_paypal,
        },
    )
    db.commit()

    return {
        "blocked": blocked,
        "member": member_public(member),
        "screening": screen.as_dict(),
        "receipt": (
            f"Enrollment refused before any payment could be set up. "
            f"{screen.explanation()} One verified PayPal account can back only one policy."
        ),
        "note": "This is a demo attack. Nothing was paid and no policy became active.",
        "pledge_display": format_inr(50_000),
    }
