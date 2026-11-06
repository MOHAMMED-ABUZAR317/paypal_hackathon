"""Payout orchestration: turn APPROVE decisions into PayPal batches exactly once.

Money rules implemented here:

* the payout box is spent first, then the reserve (as in the money-flow design);
* one Payout row per approved decision, with a unique idempotency key;
* batches are chunked, and every PayPal item id derives from the idempotency key;
* the ledger row stays PENDING until PayPal confirms it (webhook or explicit
  reconciliation) - the create response alone is not treated as settlement;
* a retry re-sends the *same* payout row, never creating a second payment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import (
    PAYOUT_CREATED,
    PAYOUT_FAILED,
    PAYOUT_PENDING,
    PAYOUT_SUCCESS,
)
from ..models import Decision, Event, Payout, Policy, Pool, utcnow
from . import audit, notifications
from .paypal import MAX_ITEMS_PER_BATCH, PayPalClient, PayPalError, get_paypal_client, to_payout_amount


@dataclass
class SpendBreakdown:
    from_payout_box: int
    from_reserve: int

    @property
    def total(self) -> int:
        return self.from_payout_box + self.from_reserve


def spend_from_pool(pool: Pool, amount_minor: int) -> SpendBreakdown:
    """Deduct from the payout box first, then the reserve. Caller commits."""
    if amount_minor <= 0:
        return SpendBreakdown(0, 0)
    from_box = min(pool.payout_balance_minor, amount_minor)
    remainder = amount_minor - from_box
    from_reserve = min(pool.reserve_balance_minor, remainder)
    if from_box + from_reserve < amount_minor:
        raise ValueError(
            f"Pool cannot cover {amount_minor} minor units "
            f"(box={pool.payout_balance_minor}, reserve={pool.reserve_balance_minor})"
        )
    pool.payout_balance_minor -= from_box
    pool.reserve_balance_minor -= from_reserve
    pool.updated_at = utcnow()
    return SpendBreakdown(from_box, from_reserve)


def refund_to_pool(pool: Pool, breakdown: SpendBreakdown) -> None:
    """Return money to the pool if PayPal definitively fails a batch."""
    pool.payout_balance_minor += breakdown.from_payout_box
    pool.reserve_balance_minor += breakdown.from_reserve
    pool.updated_at = utcnow()


def build_payout(
    *,
    decision: Decision,
    policy: Policy,
    event: Event,
    receiver: str,
    settings=None,
) -> Payout:
    settings = settings or get_settings()
    amount_minor = decision.amount_minor
    return Payout(
        decision_id=decision.id,
        event_id=event.id,
        policy_id=policy.id,
        member_id=decision.member_id,
        amount_minor=amount_minor,
        currency=policy.currency,
        send_currency=settings.paypal_payout_currency,
        send_amount=to_payout_amount(
            amount_minor, settings.paypal_payout_currency, settings.payout_inr_per_usd
        ),
        status=PAYOUT_CREATED,
        provider=get_paypal_client().provider,
        receiver=receiver,
        idempotency_key=f"payout:{event.id}:{policy.id}",
    )


def _chunks(items: list[Payout], size: int) -> Iterable[list[Payout]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _note(payout: Payout, event: Event) -> str:
    return (
        f"RainCheck payout: {event.value:g}mm rainfall in {event.zone} "
        f"crossed the policy threshold. Rs {payout.amount_minor / 100:,.0f} for "
        f"{event.days} day(s). No claim form needed."
    )[:255]


async def send_payouts(
    db: Session,
    *,
    event: Event,
    payouts: list[Payout],
    actor: str = "system",
    client: PayPalClient | None = None,
) -> dict:
    """Create one or more PayPal payout batches for already-approved payouts."""
    client = client or get_paypal_client()
    if not payouts:
        return {"batches": [], "items": 0, "provider": client.provider}

    settings = get_settings()
    batches: list[dict] = []
    for index, chunk in enumerate(_chunks(payouts, MAX_ITEMS_PER_BATCH)):
        sender_batch_id = f"rc-{event.id}-{index}"
        items = [
            {
                "sender_item_id": payout.idempotency_key,
                "receiver": payout.receiver,
                "amount": payout.send_amount,
                "currency": payout.send_currency,
                "note": _note(payout, event),
            }
            for payout in chunk
        ]
        try:
            response = await client.create_payout_batch(
                sender_batch_id=sender_batch_id,
                items=items,
                email_subject="Your RainCheck payout has arrived",
                email_message=(
                    f"Rain fell above your agreed threshold in {event.zone}. "
                    "This payout was triggered automatically - no claim was filed."
                ),
            )
        except PayPalError as exc:
            for payout in chunk:
                payout.status = PAYOUT_FAILED
                payout.failure_reason = str(exc)[:500]
                payout.attempts += 1
            audit.log(
                db,
                "payout.batch_failed",
                actor=actor,
                entity_type="event",
                entity_id=event.id,
                detail={"batch": sender_batch_id, "error": str(exc)[:400]},
            )
            batches.append({"batch_id": None, "status": "FAILED", "error": str(exc)[:400]})
            continue

        header = response.get("batch_header", {})
        batch_id = header.get("payout_batch_id")
        item_map = {
            item.get("payout_item", {}).get("sender_item_id"): item
            for item in response.get("items", [])
        }
        for payout in chunk:
            payout.batch_id = batch_id
            payout.status = PAYOUT_PENDING
            payout.provider = response.get("provider", client.provider)
            payout.attempts += 1
            matched = item_map.get(payout.idempotency_key)
            if matched:
                payout.item_id = matched.get("payout_item_id")
                # Mock mode is honest about settling locally; real mode waits for webhooks.
                if response.get("mock"):
                    payout.status = (
                        PAYOUT_SUCCESS
                        if matched.get("transaction_status") == "SUCCESS"
                        else PAYOUT_FAILED
                    )
                    if payout.status == PAYOUT_FAILED:
                        payout.failure_reason = "Mock PayPal reported a failed item"
            elif response.get("mock"):
                payout.status = PAYOUT_SUCCESS

        batches.append(
            {
                "batch_id": batch_id,
                "status": header.get("batch_status", "PENDING"),
                "items": len(chunk),
                "provider": response.get("provider", client.provider),
                "mock": bool(response.get("mock")),
            }
        )
        audit.log(
            db,
            "payout.batch_created",
            actor=actor,
            entity_type="event",
            entity_id=event.id,
            detail={
                "batch_id": batch_id,
                "items": len(chunk),
                "provider": response.get("provider", client.provider),
                "mock": bool(response.get("mock")),
                "amount_inr_minor": sum(p.amount_minor for p in chunk),
            },
        )

    db.flush()

    settled = [p for p in payouts if p.status == PAYOUT_SUCCESS]
    failed = [p for p in payouts if p.status == PAYOUT_FAILED]
    if settled and client.is_mock:
        # In mock mode there is no real webhook, so we record an explicit,
        # clearly-labelled settlement event instead of pretending one arrived.
        audit.log(
            db,
            "payout.settled_mock",
            actor=actor,
            entity_type="event",
            entity_id=event.id,
            detail={"count": len(settled), "note": "MOCK settlement, no real money moved"},
        )
    if settled:
        await notifications.notify(
            "raincheck.payout_sent",
            {
                "event_id": event.id,
                "zone": event.zone,
                "rainfall_mm": event.value,
                "payouts": len(settled),
                "total_inr_minor": sum(p.amount_minor for p in settled),
                "provider": client.provider,
            },
        )
    if failed:
        audit.log(
            db,
            "payout.items_failed",
            actor=actor,
            entity_type="event",
            entity_id=event.id,
            detail={"count": len(failed)},
        )

    return {
        "batches": batches,
        "items": len(payouts),
        "settled": len(settled),
        "failed": len(failed),
        "provider": client.provider,
        "mock": client.is_mock,
    }


async def retry_payouts(
    db: Session,
    *,
    event: Event,
    payouts: list[Payout],
    actor: str = "operator",
    client: PayPalClient | None = None,
) -> dict:
    """Re-send failed payouts. Uses a fresh batch suffix so PayPal accepts the
    items, while the Payout row (and therefore the money owed) stays unique."""
    client = client or get_paypal_client()
    if not payouts:
        return {"retried": 0, "items": 0}
    retry_index = max(p.attempts for p in payouts)
    suffix = f"retry{retry_index}"
    batches: list[dict] = []
    for index, chunk in enumerate(_chunks(payouts, MAX_ITEMS_PER_BATCH)):
        sender_batch_id = f"rc-{event.id}-{suffix}-{index}"
        items = [
            {
                "sender_item_id": f"{p.idempotency_key}:{suffix}",
                "receiver": p.receiver,
                "amount": p.send_amount,
                "currency": p.send_currency,
                "note": _note(p, event),
            }
            for p in chunk
        ]
        try:
            response = await client.create_payout_batch(sender_batch_id=sender_batch_id, items=items)
        except PayPalError as exc:
            for payout in chunk:
                payout.failure_reason = str(exc)[:500]
                payout.attempts += 1
            batches.append({"batch_id": None, "status": "FAILED", "error": str(exc)[:300]})
            continue
        header = response.get("batch_header", {})
        for payout in chunk:
            payout.batch_id = header.get("payout_batch_id")
            payout.status = PAYOUT_PENDING if not response.get("mock") else PAYOUT_SUCCESS
            payout.failure_reason = None
            payout.attempts += 1
        batches.append(
            {
                "batch_id": header.get("payout_batch_id"),
                "status": header.get("batch_status", "PENDING"),
                "items": len(chunk),
            }
        )
    audit.log(
        db,
        "payout.retried",
        actor=actor,
        entity_type="event",
        entity_id=event.id,
        detail={"payouts": len(payouts), "batches": batches},
    )
    db.flush()
    return {"retried": len(payouts), "items": len(payouts), "batches": batches}


def reconcile_batch(db: Session, batch_id: str, status: str, note: str = "") -> int:
    """Apply a verified batch-level status to every PENDING row in that batch."""
    rows = (
        db.query(Payout)
        .filter(Payout.batch_id == batch_id, Payout.status == PAYOUT_PENDING)
        .all()
    )
    mapped = {
        "SUCCESS": PAYOUT_SUCCESS,
        "FAILED": PAYOUT_FAILED,
        "DENIED": PAYOUT_FAILED,
        "RETURNED": PAYOUT_FAILED,
        "BLOCKED": PAYOUT_FAILED,
    }.get(status.upper(), PAYOUT_PENDING)
    for row in rows:
        row.status = mapped
        if mapped == PAYOUT_FAILED:
            row.failure_reason = note or f"PayPal batch status {status}"
        row.updated_at = utcnow()
    audit.log(
        db,
        "payout.batch_reconciled",
        actor="paypal",
        entity_type="batch",
        entity_id=batch_id,
        detail={"status": status, "rows": len(rows), "note": note},
    )
    return len(rows)


def payout_public(payout: Payout, *, member_name: str | None = None,
                  zone: str | None = None, reason: str | None = None) -> dict:
    return {
        "id": payout.id,
        "created_at": payout.created_at,
        "updated_at": payout.updated_at,
        "event_id": payout.event_id,
        "member_id": payout.member_id,
        "member_name": member_name,
        "zone": zone,
        "amount_minor": payout.amount_minor,
        "send_amount": payout.send_amount,
        "send_currency": payout.send_currency,
        "status": payout.status,
        "reason_code": reason,
        "provider": payout.provider,
        "batch_id": payout.batch_id,
        "item_id": payout.item_id,
        "receiver": mask_email(payout.receiver),
        "failure_reason": payout.failure_reason,
        "mock": payout.provider == "mock",
    }


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(1, len(local) - len(visible))}@{domain}"


def decision_detail(decision: Decision) -> str:
    try:
        parsed = json.loads(decision.reason_detail) if decision.reason_detail.startswith("{") else None
    except ValueError:
        parsed = None
    return parsed.get("text") if parsed else decision.reason_detail


__all__ = [
    "SpendBreakdown",
    "spend_from_pool",
    "refund_to_pool",
    "build_payout",
    "send_payouts",
    "retry_payouts",
    "reconcile_batch",
    "payout_public",
    "decision_detail",
    "mask_email",
]
