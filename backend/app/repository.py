"""Small data-access helpers used by routers and tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Pool


def get_default_pool(db: Session) -> Pool | None:
    return db.query(Pool).order_by(Pool.created_at.asc()).first()


def require_pool(db: Session) -> Pool:
    pool = get_default_pool(db)
    if pool is None:
        raise RuntimeError("No pool exists. Run the demo seed first.")
    return pool
