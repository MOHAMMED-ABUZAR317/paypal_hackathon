"""Policy parsing and enrollment.

`POST /policies/parse` is the conversational step: one sentence in, a bounded
policy preview out. `POST /policies` is the confirmation step: the preview is
re-clamped server-side, the member is screened, and the policy is stored.

Nothing here can move money.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import DEFAULT_ZONE, OUTCOME_HOLD, ZONES, format_inr
from ..db import get_db
from ..models import Member, Policy, utcnow
from ..repository import require_pool
from ..schemas import (
    EnrollRequest,
    EnrollResponse,
    PolicyParseRequest,
    PolicyParseResponse,
    PolicyPreview,
)
from ..security import enroll_limiter, parse_limiter, require_operator
from ..serializers import member_public, policy_public
from ..services import audit, receipts, screening
from ..services.policy_parser import enforce_bounds, parse_policy_text

router = APIRouter(tags=["policies"])


@router.post("/policies/parse", response_model=PolicyParseResponse)
def parse_policy(
    payload: PolicyParseRequest,
    db: Session = Depends(get_db),
    _: None = Depends(parse_limiter),
) -> PolicyParseResponse:
    if payload.zone not in ZONES:
        raise HTTPException(status_code=400, detail=f"Unknown zone '{payload.zone}'")

    outcome = parse_policy_text(payload.text, zone=payload.zone)
    if not outcome.ok or outcome.policy is None:
        return PolicyParseResponse(ok=False, error=outcome.error, attempts=outcome.attempts)

    try:
        policy = enforce_bounds(outcome.policy, source=outcome.policy.source)
    except ValueError as exc:
        return PolicyParseResponse(ok=False, error=str(exc), attempts=outcome.attempts)

    return PolicyParseResponse(ok=True, policy=policy, attempts=outcome.attempts)


@router.post("/policies", response_model=EnrollResponse, status_code=status.HTTP_201_CREATED)
def enroll(
    payload: EnrollRequest,
    db: Session = Depends(get_db),
    _: None = Depends(enroll_limiter),
) -> EnrollResponse:
    if payload.member.zone not in ZONES:
        raise HTTPException(status_code=400, detail=f"Unknown zone '{payload.member.zone}'")

    pool = require_pool(db)
    email = str(payload.member.email).lower()
    existing = db.query(Member).filter(func.lower(Member.email) == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A member with this email already exists. Use a different email or view their policy.",
        )

    try:
        policy_in = enforce_bounds(payload.policy, source="edited")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    screen = screening.screen_member(
        db,
        member_id=None,
        paypal_email=str(payload.member.paypal_email),
        device_id=payload.member.device_id,
        signup_ip=payload.member.signup_ip,
        zone=payload.member.zone,
        verified=payload.member.verified,
    )
    blocked = screen.recommendation == "block"

    member = Member(
        name=payload.member.name.strip(),
        email=email,
        paypal_email=str(payload.member.paypal_email).lower(),
        phone=payload.member.phone,
        zone=payload.member.zone,
        device_id=payload.member.device_id,
        signup_ip=payload.member.signup_ip,
        verified=payload.member.verified,
        status="blocked" if blocked else "active",
        created_at=utcnow(),
    )
    db.add(member)
    db.flush()

    policy = Policy(
        member_id=member.id,
        pool_id=pool.id,
        schema_version=policy_in.schema_version,
        trigger_type=policy_in.trigger_type,
        data_source=policy_in.data_source,
        zone=payload.member.zone,
        metric=policy_in.metric,
        comparator=policy_in.operator,
        threshold=policy_in.threshold,
        payout_amount_minor=policy_in.payout_amount_minor,
        currency="INR",
        max_payouts_per_day=policy_in.max_payouts_per_day,
        max_payouts_per_month=policy_in.max_payouts_per_month,
        waiting_period_hours=policy_in.waiting_period_hours,
        active=not blocked,
        starts_at=utcnow(),
        source_text=payload.source_text,
        parser_source=policy_in.source,
        risk_score=screen.score,
        risk_flags=json.dumps([f.code for f in screen.flags]),
    )
    db.add(policy)
    db.flush()

    receipt = receipts.policy_receipt(
        name=member.name,
        zone=member.zone,
        threshold=policy.threshold,
        payout_minor=policy.payout_amount_minor,
        monthly_cap=policy.max_payouts_per_month,
        waiting_hours=policy.waiting_period_hours,
    )

    audit.log(
        db,
        "member.blocked_at_enrollment" if blocked else "member.enrolled",
        actor="member",
        entity_type="member",
        entity_id=member.id,
        detail={
            "policy_id": policy.id,
            "zone": member.zone,
            "risk_score": screen.score,
            "flags": [f.code for f in screen.flags],
            "payout_minor": policy.payout_amount_minor,
            "threshold_mm": policy.threshold,
            "parser_source": policy.parser_source,
        },
    )
    if blocked:
        audit.log(
            db,
            "fraud.enrollment_blocked",
            actor="rules",
            entity_type="member",
            entity_id=member.id,
            detail={"reason": screen.explanation(), "flags": [f.code for f in screen.flags]},
        )

    db.commit()
    db.refresh(member)
    db.refresh(policy)

    return EnrollResponse(
        member=member_public(member),
        policy=policy_public(policy),
        screening=screen.as_dict(),
        receipt=receipt,
        blocked=blocked,
    )


@router.get("/policies")
def list_policies(
    member_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Policy)
    if member_id:
        query = query.filter(Policy.member_id == member_id)
    rows = query.order_by(Policy.created_at.desc()).limit(limit).all()
    return {"policies": [policy_public(row) for row in rows]}


@router.get("/members")
def list_members(
    q: str | None = Query(default=None, description="Name or email search"),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Member)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Member.name).like(like) | func.lower(Member.email).like(like)
        )
    rows = query.order_by(Member.created_at.desc()).limit(limit).all()
    return {"members": [member_public(row) for row in rows]}


@router.get("/members/{member_id}")
def get_member(member_id: str, db: Session = Depends(get_db)) -> dict:
    member = db.query(Member).filter(Member.id == member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    policies = db.query(Policy).filter(Policy.member_id == member_id).all()
    from .ledger import receipts_for_member

    return {
        "member": member_public(member),
        "policies": [policy_public(row) for row in policies],
        "receipts": receipts_for_member(db, member_id, limit=10),
        "pledge_display": (
            format_inr(policies[0].payout_amount_minor) if policies else None
        ),
        "hold_note": (
            "This account has open risk flags; any payout will be held for human review."
            if member.status == "blocked"
            else None
        ),
    }


@router.patch("/policies/{policy_id}")
def set_policy_status(
    policy_id: str,
    active: bool = Query(..., description="true to activate, false to deactivate"),
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    policy.active = active
    audit.log(
        db,
        "policy.updated",
        actor="operator",
        entity_type="policy",
        entity_id=policy.id,
        detail={"active": active},
    )
    db.commit()
    return {"policy": policy_public(policy)}
