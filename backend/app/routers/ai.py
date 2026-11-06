"""AI endpoints. Every response states whether a model or a fallback produced it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Event, Member, Payout
from ..repository import require_pool
from ..security import RateLimiter, require_operator
from ..services import ai

router = APIRouter(tags=["ai"])
ai_limiter = RateLimiter(limit=20, window_seconds=60)


@router.get("/ai/status")
def status() -> dict:
    return ai.ai_status()


@router.post("/ai/member/{member_id}/review")
async def review_member(
    member_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    member = db.query(Member).filter(Member.id == member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return await ai.review_member(db, member)


@router.post("/ai/event/{event_id}/review")
async def review_event(
    event_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return await ai.review_event(db, event)


@router.get("/ai/pool-insight")
async def pool_insight(db: Session = Depends(get_db)) -> dict:
    return await ai.forecast_insight(db, require_pool(db))


@router.post("/ai/receipts/{payout_id}/explain")
async def explain_receipt(
    payout_id: str,
    language: str = Query(default="en", pattern="^(en|hi|te)$"),
    db: Session = Depends(get_db),
    _: None = Depends(ai_limiter),
) -> dict:
    payout = db.query(Payout).filter(Payout.id == payout_id).first()
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    try:
        return await ai.explain_receipt(db, payout_id, language)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
