"""Pool health: balance, coverage runway and a plain-language forecast."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import DEMO_PAYOUT_MINOR, OUTCOME_APPROVE
from ..models import Decision, Member, Policy, Pool


def pool_forecast(db: Session, pool: Pool) -> dict:
    active_policies = (
        db.query(func.count(Policy.id))
        .filter(Policy.pool_id == pool.id, Policy.active.is_(True))
        .scalar()
        or 0
    )
    verified_members = (
        db.query(func.count(Member.id))
        .filter(Member.status == "active", Member.verified.is_(True))
        .scalar()
        or 0
    )

    # Members per zone tells us how big a single-zone storm payout could be.
    per_zone = (
        db.query(Policy.zone, func.count(Policy.id))
        .filter(Policy.pool_id == pool.id, Policy.active.is_(True))
        .group_by(Policy.zone)
        .all()
    )
    zone_counts = {zone: count for zone, count in per_zone}
    biggest_zone = max(zone_counts.values()) if zone_counts else 0

    avg_payout = (
        db.query(func.avg(Decision.amount_minor))
        .filter(Decision.outcome == OUTCOME_APPROVE)
        .scalar()
    )
    expected_per_member = int(avg_payout) if avg_payout else DEMO_PAYOUT_MINOR

    # Stress assumption: a single storm hits 15% of a zone, not the whole zone.
    # This mirrors the money-flow document (400 of 10,000 members in one storm)
    # and is stated openly in the UI so nobody mistakes it for a guarantee.
    stress_fraction = 0.15
    assumed_affected = max(1, int(round(biggest_zone * stress_fraction)))
    expected_event_cost = assumed_affected * expected_per_member

    total = pool.total_balance_minor
    if expected_event_cost > 0:
        events_covered = total / expected_event_cost
    else:
        events_covered = 0.0

    monthly_inflow = (
        db.query(func.count(Policy.id))
        .filter(Policy.pool_id == pool.id, Policy.active.is_(True))
        .scalar()
        or 0
    ) * pool.contribution_amount_minor

    narrative = (
        f"The pool holds Rs {total / 100:,.0f}. Assuming a storm hits about "
        f"{stress_fraction:.0%} of the largest zone ({assumed_affected:,} members x "
        f"Rs {expected_per_member / 100:,.0f}), one event costs about "
        f"Rs {expected_event_cost / 100:,.0f}. Current funds cover roughly "
        f"{min(events_covered, 99):.1f} such event(s)."
    )
    if events_covered < 1:
        narrative += " Cover is under one worst-case event: the operator should cap, raise contributions, or pause."
    elif events_covered < 3:
        narrative += " That is thin for a bad month; the reserve exists for exactly this."
    else:
        narrative += " Coverage looks healthy for the demo scenario."

    return {
        "active_policies": active_policies,
        "verified_members": verified_members,
        "zone_counts": zone_counts,
        "biggest_zone": biggest_zone,
        "stress_fraction": stress_fraction,
        "assumed_affected_members": assumed_affected,
        "expected_payout_per_member_minor": expected_per_member,
        "expected_event_cost_minor": expected_event_cost,
        "events_covered": round(events_covered, 2),
        "monthly_inflow_minor": monthly_inflow,
        "narrative": narrative,
        "source": "rules",
    }
