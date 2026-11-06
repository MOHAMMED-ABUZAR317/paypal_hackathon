"""Split incoming contributions the same way the money-flow design does."""

from __future__ import annotations

from ..models import Pool

PAYOUT_SHARE = 70
RESERVE_SHARE = 20


def credit_contribution(pool: Pool, amount_minor: int) -> dict:
    """70% payout box, 20% reserve, 10% running costs (integer-safe)."""
    if amount_minor <= 0:
        return {"payout_box": 0, "reserve": 0, "running_costs": 0}
    payout_box = amount_minor * PAYOUT_SHARE // 100
    reserve = amount_minor * RESERVE_SHARE // 100
    running = amount_minor - payout_box - reserve
    pool.payout_balance_minor += payout_box
    pool.reserve_balance_minor += reserve
    pool.running_costs_minor += running
    return {"payout_box": payout_box, "reserve": reserve, "running_costs": running}
