"""Read-only views: the payout ledger, decisions, receipts and the audit log."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import format_inr
from ..db import get_db
from ..models import AuditLog, Decision, Event, Member, Payout, Policy
from ..serializers import iso_z, payout_public
from ..services import receipts

router = APIRouter(tags=["ledger"])


def _receipt_for(
    payout: Payout, decision: Decision | None, member: Member | None,
    event: Event | None, policy: Policy | None
) -> dict:
    text = receipts.payout_receipt(
        name=member.name if member else "Member",
        outcome=decision.outcome if decision else "APPROVE",
        reason_code=decision.reason_code if decision else "OK",
        reason_detail=decision.reason_detail if decision else "",
        amount_minor=payout.amount_minor,
        payable_days=decision.payable_days if decision else event.days if event else 1,
        zone=event.zone if event else (member.zone if member else ""),
        rainfall_mm=event.value if event else None,
        threshold=policy.threshold if policy else None,
        status=payout.status,
        provider=payout.provider,
        send_amount=payout.send_amount,
        send_currency=payout.send_currency,
    )
    return {
        "id": f"rcpt_{payout.id}",
        "payout_id": payout.id,
        "created_at": iso_z(payout.created_at),
        "member_id": payout.member_id,
        "member_name": member.name if member else None,
        "amount_minor": payout.amount_minor,
        "amount_display": format_inr(payout.amount_minor),
        "status": payout.status,
        "provider": payout.provider,
        "zone": event.zone if event else None,
        "rainfall_mm": event.value if event else None,
        "text": text,
    }


def receipts_for_member(db: Session, member_id: str, limit: int = 10) -> list[dict]:
    rows = (
        db.query(Payout, Decision, Event, Policy, Member)
        .join(Decision, Payout.decision_id == Decision.id)
        .join(Event, Payout.event_id == Event.id)
        .join(Policy, Payout.policy_id == Policy.id)
        .join(Member, Payout.member_id == Member.id)
        .filter(Payout.member_id == member_id)
        .order_by(Payout.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        _receipt_for(payout, decision, member, event, policy)
        for payout, decision, event, policy, member in rows
    ]


@router.get("/ledger")
def ledger(
    status_filter: str | None = Query(default=None, alias="status"),
    zone: str | None = Query(default=None),
    event_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    query = (
        db.query(Payout, Member, Event, Decision)
        .join(Member, Payout.member_id == Member.id)
        .join(Event, Payout.event_id == Event.id)
        .join(Decision, Payout.decision_id == Decision.id)
    )
    if status_filter:
        query = query.filter(Payout.status == status_filter.upper())
    if zone:
        query = query.filter(Event.zone == zone)
    if event_id:
        query = query.filter(Payout.event_id == event_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Member.name).like(like) | func.lower(Member.email).like(like)
        )

    total = query.count()
    rows = query.order_by(Payout.created_at.desc()).offset(offset).limit(limit).all()
    counts = dict(
        db.query(Payout.status, func.count(Payout.id)).group_by(Payout.status).all()
    )
    return {
        "rows": [
            payout_public(payout, member=member, event=event, reason_code=decision.reason_code)
            for payout, member, event, decision in rows
        ],
        "total": total,
        "counts": counts,
        "limit": limit,
        "offset": offset,
        "mock": all(payout.provider == "mock" for payout, *_ in rows) if rows else True,
    }


@router.get("/decisions")
def decisions(
    event_id: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Decision, Member).join(Member, Decision.member_id == Member.id)
    if event_id:
        query = query.filter(Decision.event_id == event_id)
    if outcome:
        query = query.filter(Decision.outcome == outcome.upper())
    rows = query.order_by(Decision.created_at.desc()).limit(limit).all()
    return {
        "decisions": [
            {
                "id": decision.id,
                "event_id": decision.event_id,
                "member_id": decision.member_id,
                "member_name": member.name,
                "outcome": decision.outcome,
                "reason_code": decision.reason_code,
                "reason_detail": decision.reason_detail,
                "risk_score": decision.risk_score,
                "payable_days": decision.payable_days,
                "amount_minor": decision.amount_minor,
                "amount_display": format_inr(decision.amount_minor),
                "created_at": iso_z(decision.created_at),
            }
            for decision, member in rows
        ]
    }


@router.get("/receipts")
def receipts_feed(
    member_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    if member_id:
        return {"receipts": receipts_for_member(db, member_id, limit=limit)}
    rows = (
        db.query(Payout, Decision, Event, Policy, Member)
        .join(Decision, Payout.decision_id == Decision.id)
        .join(Event, Payout.event_id == Event.id)
        .join(Policy, Payout.policy_id == Policy.id)
        .join(Member, Payout.member_id == Member.id)
        .order_by(Payout.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "receipts": [
            _receipt_for(payout, decision, member, event, policy)
            for payout, decision, event, policy, member in rows
        ]
    }


@router.get("/receipts/{payout_id}")
def receipt_detail(payout_id: str, db: Session = Depends(get_db)) -> dict:
    row = (
        db.query(Payout, Decision, Event, Policy, Member)
        .join(Decision, Payout.decision_id == Decision.id)
        .join(Event, Payout.event_id == Event.id)
        .join(Policy, Payout.policy_id == Policy.id)
        .join(Member, Payout.member_id == Member.id)
        .filter(Payout.id == payout_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    payout, decision, event, policy, member = row
    return {"receipt": _receipt_for(payout, decision, member, event, policy)}


@router.get("/audit")
def audit_feed(
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(limit).all()
    return {
        "entries": [
            {
                "id": entry.id,
                "ts": iso_z(entry.ts),
                "actor": entry.actor,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "detail": json.loads(entry.detail_json or "{}"),
            }
            for entry in rows
        ]
    }
