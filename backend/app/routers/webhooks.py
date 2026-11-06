"""PayPal webhook receiver.

Rules:
* the signature is verified *before* any state change;
* handlers are idempotent (PayPal retries deliveries);
* unknown event types are acknowledged, not guessed at;
* money is only credited when a contribution transitions to COMPLETED, and only
  once, so a replayed capture webhook cannot inflate the pool.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..constants import (
    PAYOUT_FAILED,
    PAYOUT_SUCCESS,
)
from ..db import get_db
from ..models import Contribution, Payout, utcnow
from ..services import audit, notifications
from ..services.paypal import get_paypal_client
from ..services.payout_service import reconcile_batch
from ..services.pool_money import credit_contribution
from ..repository import get_default_pool

logger = logging.getLogger("raincheck.webhooks")
router = APIRouter(tags=["webhooks"])

PAYOUT_SUCCESS_EVENTS = {"PAYMENT.PAYOUTS-ITEM.SUCCEEDED"}
PAYOUT_FAILURE_EVENTS = {
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.DENIED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
}


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    client = get_paypal_client()

    verification = await client.verify_webhook(headers, body)
    try:
        event = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError):
        event = {}

    event_type = event.get("event_type", "UNKNOWN")
    resource = event.get("resource") or {}

    if not verification.verified:
        audit.log(
            db,
            "webhook.rejected",
            actor="paypal",
            entity_type="webhook",
            entity_id=event.get("id"),
            detail={
                "event_type": event_type,
                "reason": verification.reason,
                "mode": verification.mode,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook signature rejected: {verification.reason}",
        )

    handled = False
    changed = 0

    if event_type in PAYOUT_SUCCESS_EVENTS or event_type in PAYOUT_FAILURE_EVENTS:
        success = event_type in PAYOUT_SUCCESS_EVENTS
        item_id = resource.get("payout_item_id")
        batch_id = resource.get("payout_batch_id")
        payout = None
        if item_id:
            payout = db.query(Payout).filter(Payout.item_id == item_id).first()
        if payout is None and batch_id:
            receiver = (resource.get("payout_item") or {}).get("receiver")
            query = db.query(Payout).filter(Payout.batch_id == batch_id)
            if receiver:
                query = query.filter(Payout.receiver == receiver)
            payout = query.first()
        if payout is not None:
            payout.status = PAYOUT_SUCCESS if success else PAYOUT_FAILED
            payout.provider = "paypal"
            payout.updated_at = utcnow()
            if not success:
                payout.failure_reason = (
                    resource.get("errors", {}).get("message")
                    if isinstance(resource.get("errors"), dict)
                    else f"PayPal item status {event_type}"
                )
            changed = 1
            handled = True
            audit.log(
                db,
                "webhook.payout_item",
                actor="paypal",
                entity_type="payout",
                entity_id=payout.id,
                detail={
                    "event_type": event_type,
                    "item_id": item_id,
                    "batch_id": batch_id,
                    "status": payout.status,
                },
            )
            if success:
                await notifications.notify(
                    "raincheck.payout_settled",
                    {
                        "payout_id": payout.id,
                        "amount_minor": payout.amount_minor,
                        "provider": "paypal",
                    },
                )

    elif event_type.startswith("PAYMENT.PAYOUTSBATCH."):
        batch_id = resource.get("payout_batch_id") or (resource.get("batch_header") or {}).get(
            "payout_batch_id"
        )
        batch_status = resource.get("batch_status") or (resource.get("batch_header") or {}).get(
            "batch_status", ""
        )
        if batch_id and batch_status:
            changed = reconcile_batch(db, batch_id, batch_status)
            handled = changed > 0
            audit.log(
                db,
                "webhook.batch",
                actor="paypal",
                entity_type="batch",
                entity_id=batch_id,
                detail={"event_type": event_type, "batch_status": batch_status, "rows": changed},
            )

    elif event_type in {"PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED"}:
        order_id = (
            ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get(
                "order_id"
            )
        )
        capture_id = resource.get("id")
        contribution = None
        if order_id:
            contribution = (
                db.query(Contribution).filter(Contribution.order_id == order_id).first()
            )
        if contribution is None and capture_id:
            contribution = (
                db.query(Contribution)
                .filter(Contribution.capture_id == capture_id)
                .first()
            )
        if contribution is not None:
            handled = True
            if event_type == "PAYMENT.CAPTURE.COMPLETED":
                if contribution.status != "COMPLETED":
                    pool = get_default_pool(db)
                    split = credit_contribution(pool, contribution.amount_minor) if pool else {}
                    contribution.status = "COMPLETED"
                    contribution.capture_id = capture_id
                    contribution.provider = "paypal"
                    changed = 1
                else:
                    split = {"note": "already credited (idempotent replay)"}
            else:
                contribution.status = "FAILED"
                split = {}
                changed = 1
            audit.log(
                db,
                "webhook.capture",
                actor="paypal",
                entity_type="contribution",
                entity_id=contribution.id,
                detail={
                    "event_type": event_type,
                    "order_id": order_id,
                    "capture_id": capture_id,
                    "split": split,
                },
            )

    audit.log(
        db,
        "webhook.received",
        actor="paypal",
        entity_type="webhook",
        entity_id=event.get("id"),
        detail={
            "event_type": event_type,
            "mode": verification.mode,
            "handled": handled,
            "rows_changed": changed,
        },
    )
    db.commit()
    return {
        "status": "ok",
        "event_type": event_type,
        "handled": handled,
        "rows_changed": changed,
        "verification": verification.mode,
    }
