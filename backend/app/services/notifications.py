"""Optional Zapier notification ("your payout landed").

Disabled unless ZAPIER_WEBHOOK_URL is set. Failures never block a payout: the
money movement is already committed in the ledger.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger("raincheck.notify")


async def notify(event_name: str, payload: dict[str, Any]) -> bool:
    settings = get_settings()
    if not settings.zapier_webhook_url:
        return False
    body = {"event": event_name, **payload}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(settings.zapier_webhook_url, json=body)
        return response.status_code < 400
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Zapier notification failed: %s", exc)
        return False
