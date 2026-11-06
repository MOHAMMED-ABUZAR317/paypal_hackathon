"""Live trigger scheduler: Open-Meteo rainfall -> normalised event -> payout run.

A real deployment polls every few minutes. The demo never depends on the
weather: the operator's Simulate Event button produces the exact same event
shape through the exact same pipeline.

Feed failures are fail-closed: no event is created, an audit entry is written,
and the operator can see it. A stale or unavailable feed can never pay anyone.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import (
    DATA_SOURCE_OPEN_METEO,
    DEMO_THRESHOLD_MM,
    TRIGGER_RAINFALL,
    ZONES,
)
from ..db import SessionLocal
from ..models import Event, Policy, Pool
from . import audit, trigger
from .rules import as_utc

logger = logging.getLogger("raincheck.scheduler")


def _pool(db: Session) -> Pool | None:
    return db.query(Pool).order_by(Pool.created_at.asc()).first()


async def fetch_zone_rainfall(zone_id: str, timeout: float = 12.0) -> dict:
    """Return today's 24h precipitation sum for one zone, or raise."""
    zone = ZONES[zone_id]
    settings = get_settings()
    params = {
        "latitude": zone.latitude,
        "longitude": zone.longitude,
        "daily": "precipitation_sum",
        "timezone": "Asia/Kolkata",
        "forecast_days": 1,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(settings.open_meteo_base, params=params)
    response.raise_for_status()
    payload = response.json()
    daily = payload.get("daily") or {}
    values = daily.get("precipitation_sum") or []
    if not values or values[0] is None:
        raise ValueError("Open-Meteo returned no precipitation_sum for today")
    return {
        "zone": zone_id,
        "value_mm": float(values[0]),
        "date": (daily.get("time") or [None])[0],
        "raw": payload,
    }


def _zone_threshold(db: Session, pool: Pool, zone_id: str) -> float:
    value = (
        db.query(Policy.threshold)
        .filter(
            Policy.pool_id == pool.id,
            Policy.zone == zone_id,
            Policy.trigger_type == TRIGGER_RAINFALL,
            Policy.active.is_(True),
        )
        .order_by(Policy.threshold.asc())
        .limit(1)
        .scalar()
    )
    return float(value if value is not None else DEMO_THRESHOLD_MM)


async def poll_zone(db: Session, pool: Pool, zone_id: str, *, actor: str = "scheduler") -> dict:
    try:
        reading = await fetch_zone_rainfall(zone_id)
    except Exception as exc:
        audit.log(
            db,
            "feed.unavailable",
            actor=actor,
            entity_type="zone",
            entity_id=zone_id,
            detail={"source": DATA_SOURCE_OPEN_METEO, "error": str(exc)[:300]},
        )
        db.commit()
        return {"zone": zone_id, "status": "feed_error", "error": str(exc)[:200]}

    threshold = _zone_threshold(db, pool, zone_id)
    if reading["value_mm"] < threshold:
        return {
            "zone": zone_id,
            "status": "below_threshold",
            "value_mm": reading["value_mm"],
            "threshold_mm": threshold,
        }

    day = reading.get("date") or datetime.now(timezone.utc).date().isoformat()
    payload = trigger.normalise_rainfall_event(
        zone=zone_id,
        value=reading["value_mm"],
        days=1,
        mode="live",
        event_key=f"live:{zone_id}:{day}",
        data_source=DATA_SOURCE_OPEN_METEO,
        raw={"daily": (reading.get("raw") or {}).get("daily", {})},
        threshold=threshold,
    )
    summary = await trigger.ingest_event(db, pool, payload, actor=actor)
    return {
        "zone": zone_id,
        "status": "duplicate" if summary.get("duplicate") else "processed",
        "value_mm": reading["value_mm"],
        "threshold_mm": threshold,
        "event_id": summary["event"]["id"],
        "counts": summary.get("counts"),
        "total_paid_minor": summary.get("total_paid_minor"),
    }


async def poll_all_zones(db: Session, *, actor: str = "scheduler") -> list[dict]:
    pool = _pool(db)
    if pool is None:
        return []
    results = []
    for zone_id in ZONES:
        results.append(await poll_zone(db, pool, zone_id, actor=actor))
    return results


def next_poll_estimate() -> str | None:
    settings = get_settings()
    if settings.poll_interval_minutes <= 0:
        return None
    now = datetime.now(timezone.utc)
    minutes = settings.poll_interval_minutes
    upcoming = now.replace(second=0, microsecond=0)
    upcoming = upcoming.replace(minute=(upcoming.minute // minutes) * minutes)
    if upcoming <= now:
        upcoming = upcoming.replace(minute=0) if minutes >= 60 else upcoming
    return as_utc(upcoming).isoformat()


async def scheduler_loop() -> None:
    settings = get_settings()
    interval = settings.poll_interval_minutes
    if interval <= 0:
        logger.info("Live polling disabled (POLL_INTERVAL_MINUTES=0)")
        return
    logger.info("RainCheck live poller started (%s minute interval)", interval)
    while True:
        db = SessionLocal()
        try:
            if _pool(db) is not None:
                results = await poll_all_zones(db, actor="scheduler")
                fired = [r for r in results if r["status"] == "processed"]
                if fired:
                    logger.info("Live triggers fired: %s", fired)
        except asyncio.CancelledError:
            db.close()
            raise
        except Exception:  # pragma: no cover - defensive
            logger.exception("Scheduler pass failed")
        finally:
            db.close()
        await asyncio.sleep(interval * 60)
