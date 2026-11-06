"""Pool funding through PayPal Orders, plus pool stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Contribution, Member, utcnow
from ..repository import require_pool
from ..schemas import FundRequest, FundResponse
from ..security import fund_limiter
from ..serializers import contribution_public, iso_z
from ..services import audit
from ..services.paypal import PayPalError, get_paypal_client
from ..services.pool_money import credit_contribution
from ..services.stats import pool_public, pool_stats

router = APIRouter(tags=["pool"])


@router.get("/pool")
def get_pool(db: Session = Depends(get_db)) -> dict:
    return {"pool": pool_public(require_pool(db))}


@router.get("/pool/stats")
def get_pool_stats(db: Session = Depends(get_db)) -> dict:
    return pool_stats(db, require_pool(db))


def _fund_response(row: Contribution, *, approve_url: str | None = None) -> FundResponse:
    return FundResponse(
        contribution_id=row.id,
        order_id=row.order_id or "",
        provider=row.provider,
        mock=row.provider == "mock",
        approve_url=approve_url,
        amount_minor=row.amount_minor,
        currency=row.currency,
        status=row.status,
    )


@router.post("/pool/fund", response_model=FundResponse)
async def fund_pool(
    payload: FundRequest,
    db: Session = Depends(get_db),
    _: None = Depends(fund_limiter),
) -> FundResponse:
    settings = get_settings()
    pool = require_pool(db)
    member = db.query(Member).filter(Member.id == payload.member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    amount_minor = payload.amount_minor or pool.contribution_amount_minor
    period = utcnow().strftime("%Y-%m")
    idempotency_key = f"fund:{member.id}:{period}:{amount_minor}"

    existing = (
        db.query(Contribution)
        .filter(Contribution.idempotency_key == idempotency_key)
        .first()
    )
    if existing and existing.status == "COMPLETED":
        return _fund_response(existing)

    client = get_paypal_client()
    reference = f"RC-{member.id[-6:]}-{period}"
    try:
        order = await client.create_order(
            amount_minor=amount_minor,
            currency=pool.currency,
            description=f"RainCheck pool contribution for {member.name}",
            reference_id=reference,
            idempotency_key=idempotency_key,
        )
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=f"PayPal order failed: {exc}") from exc

    approve_url = next(
        (link.get("href") for link in order.get("links", []) if link.get("rel") in {"approve", "payer-action"}),
        None,
    )
    if existing:
        row = existing
        row.order_id = order.get("id")
        row.status = "CREATED"
    else:
        row = Contribution(
            member_id=member.id,
            pool_id=pool.id,
            amount_minor=amount_minor,
            currency=pool.currency,
            status="CREATED",
            provider=order.get("provider", client.provider),
            order_id=order.get("id"),
            idempotency_key=idempotency_key,
        )
        db.add(row)

    audit.log(
        db,
        "pool.funding_started",
        actor="member",
        entity_type="member",
        entity_id=member.id,
        detail={
            "order_id": order.get("id"),
            "amount_minor": amount_minor,
            "provider": order.get("provider", client.provider),
            "mock": bool(order.get("mock")),
        },
    )
    db.commit()
    db.refresh(row)
    return _fund_response(row, approve_url=approve_url if not order.get("mock") else None)


@router.post("/pool/fund/{order_id}/capture", response_model=FundResponse)
async def capture_funding(order_id: str, db: Session = Depends(get_db)) -> FundResponse:
    pool = require_pool(db)
    row = db.query(Contribution).filter(Contribution.order_id == order_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Funding order not found")
    if row.status == "COMPLETED":
        return _fund_response(row)

    client = get_paypal_client()
    try:
        capture = await client.capture_order(order_id)
    except PayPalError as exc:
        row.status = "FAILED"
        audit.log(
            db,
            "pool.funding_failed",
            actor="paypal",
            entity_type="contribution",
            entity_id=row.id,
            detail={"order_id": order_id, "error": str(exc)[:300]},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=f"PayPal capture failed: {exc}") from exc

    if capture.get("status") != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"PayPal did not complete the capture (status={capture.get('status')})",
        )

    capture_id = None
    try:
        purchase_units = capture.get("purchase_units") or []
        captures = (purchase_units[0].get("payments") or {}).get("captures") or []
        capture_id = captures[0].get("id") if captures else None
    except (IndexError, AttributeError):
        capture_id = None

    split = credit_contribution(pool, row.amount_minor)
    row.status = "COMPLETED"
    row.capture_id = capture_id
    row.provider = capture.get("provider", client.provider)
    audit.log(
        db,
        "pool.funded",
        actor="paypal",
        entity_type="contribution",
        entity_id=row.id,
        detail={
            "order_id": order_id,
            "capture_id": capture_id,
            "amount_minor": row.amount_minor,
            "split": split,
            "provider": row.provider,
            "mock": bool(capture.get("mock")),
        },
    )
    db.commit()
    db.refresh(row)
    return _fund_response(row)


@router.get("/contributions")
def list_contributions(
    member_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Contribution)
    if member_id:
        query = query.filter(Contribution.member_id == member_id)
    rows = query.order_by(Contribution.created_at.desc()).limit(limit).all()
    total = (
        db.query(func.coalesce(func.sum(Contribution.amount_minor), 0))
        .filter(Contribution.status == "COMPLETED")
        .scalar()
        or 0
    )
    return {
        "contributions": [contribution_public(row) for row in rows],
        "completed_total_minor": int(total),
        "completed_total_display": f"Rs {int(total) / 100:,.2f}",
    }
