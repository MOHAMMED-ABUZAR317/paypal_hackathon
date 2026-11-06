"""Event ingestion endpoints: demo injection, live polling and history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..constants import ZONES
from ..db import get_db
from ..models import Event
from ..repository import require_pool
from ..schemas import SimulateEventRequest
from ..security import require_operator
from ..services import scheduler, trigger

router = APIRouter(tags=["events"])


@router.post("/events/simulate")
async def simulate_event(
    payload: SimulateEventRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    """Demo-safe trigger. Same event shape, same pipeline, same guardrails."""
    if payload.zone not in ZONES:
        raise HTTPException(status_code=400, detail=f"Unknown zone '{payload.zone}'")
    if payload.trigger_type != "rainfall":
        raise HTTPException(
            status_code=400,
            detail="This prototype supports rainfall triggers only.",
        )
    pool = require_pool(db)
    try:
        normalised = trigger.normalise_rainfall_event(
            zone=payload.zone,
            value=payload.rainfall_mm,
            days=payload.days,
            mode="simulated",
            event_key=payload.event_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await trigger.ingest_event(db, pool, normalised, actor="operator")


@router.post("/events/poll")
async def poll_live(
    db: Session = Depends(get_db),
    _: str = Depends(require_operator),
) -> dict:
    """Poll Open-Meteo now instead of waiting for the scheduler."""
    results = await scheduler.poll_all_zones(db, actor="operator")
    fired = [row for row in results if row.get("status") == "processed"]
    return {
        "results": results,
        "zones_checked": len(results),
        "events_fired": len(fired),
        "note": "Feed errors are fail-closed: no event, no payout.",
    }


@router.get("/events")
def list_events(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    pool = require_pool(db)
    rows = (
        db.query(Event)
        .filter(Event.pool_id == pool.id)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"events": [trigger.event_public(row) for row in rows]}


@router.get("/events/{event_id}")
def get_event(event_id: str, db: Session = Depends(get_db)) -> dict:
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return trigger.event_summary(db, event)


@router.get("/events/{event_id}/last-key")
def event_key(event_id: str, db: Session = Depends(get_db)) -> dict:
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"event_id": event.id, "event_key": event.event_key}
