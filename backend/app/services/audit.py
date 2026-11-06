"""Append-only audit log.

Every operator action, AI decision, rule outcome, payout and webhook landing
writes here. The log is exposed read-only at `GET /api/audit`.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog


def log(
    db: Session,
    action: str,
    *,
    actor: str = "system",
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=json.dumps(detail or {}, default=str, separators=(",", ":")),
        request_id=request_id,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
