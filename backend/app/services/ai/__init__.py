"""AI layer.

Design constraints, enforced by code and by a test:

* the AI cannot import or call PayPal;
* every model output passes a strict schema and server-side bounds before use;
* if the model is missing, slow, or wrong, the deterministic path answers;
* the AI never returns a decision - only a proposal or an advisory explanation.
"""

from .service import (
    ai_status,
    explain_receipt,
    forecast_insight,
    parse_policy,
    review_event,
    review_member,
)

__all__ = [
    "ai_status",
    "parse_policy",
    "review_member",
    "review_event",
    "forecast_insight",
    "explain_receipt",
]
