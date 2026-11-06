"""Health, configuration and zone metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..constants import ZONES
from ..db import get_db
from ..models import Event, Member, Pool
from ..services.stats import pool_stats
from ..repository import get_default_pool

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    members = db.query(func.count(Member.id)).scalar() or 0
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.env,
        "database": "ok",
        "seeded": bool(db.query(func.count(Pool.id)).scalar()),
        "members": int(members),
        "paypal_mode": "sandbox" if settings.use_real_paypal else "mock",
        "ai_mode": "llm" if settings.ai_configured else "deterministic-fallback",
    }


@router.get("/config")
def public_config() -> dict:
    settings = get_settings()
    return {
        "app": settings.public_config(),
        "zones": [
            {
                "id": zone.id,
                "name": zone.name,
                "city": zone.city,
                "latitude": zone.latitude,
                "longitude": zone.longitude,
            }
            for zone in ZONES.values()
        ],
        "limits": {
            "max_payouts_per_day": 1,
            "max_payouts_per_month": 3,
            "min_threshold_mm": 5,
            "max_threshold_mm": 300,
            "min_payout_minor": 5_000,
            "max_payout_minor": 200_000,
        },
    }


@router.get("/zones")
def zones() -> dict:
    return {
        "zones": [
            {
                "id": zone.id,
                "name": zone.name,
                "city": zone.city,
                "latitude": zone.latitude,
                "longitude": zone.longitude,
            }
            for zone in ZONES.values()
        ]
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    pool = get_default_pool(db)
    if pool is None:
        return {"seeded": False, "stats": None, "recent_events": []}
    events = (
        db.query(Event)
        .filter(Event.pool_id == pool.id)
        .order_by(Event.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "seeded": True,
        "stats": pool_stats(db, pool),
        "recent_events": [
            {
                "id": event.id,
                "zone": event.zone,
                "value": event.value,
                "days": event.days,
                "mode": event.mode,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }
