"""Auth and abuse limits for the operator surface.

The operator console is a prototype surface: a single shared key, clearly
documented as demo-only. Production would use SSO + per-action audit, which the
README states openly.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Header, HTTPException, Request, status

from .config import get_settings


def require_operator(x_operator_key: str = Header(default="", alias="X-Operator-Key")) -> str:
    """Every /operator and /events/simulate route requires this header."""
    expected = get_settings().operator_api_key
    if not x_operator_key or not hmac.compare_digest(x_operator_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Operator key required. Send the X-Operator-Key header. "
                "See OPERATOR_API_KEY in .env."
            ),
        )
    return "operator"


class RateLimiter:
    """Small in-process sliding-window limiter (demo scale, no Redis needed)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please wait a moment and try again.",
                )
            bucket.append(now)


parse_limiter = RateLimiter(limit=30, window_seconds=60)
enroll_limiter = RateLimiter(limit=20, window_seconds=60)
fund_limiter = RateLimiter(limit=30, window_seconds=60)
