"""Deterministic demo seed.

Creates a realistic 10,000-member pool so the dashboard, ledger and forecast
look like a product rather than a blank page. Everything is generated from a
fixed RNG seed, so screenshots and the video are reproducible.

The seed also contains the deliberate bad actors used in the fraud demo:
  * a ring of accounts sharing one PayPal payout address and device;
  * unverified accounts that must go to HOLD_FOR_REVIEW;
  * brand-new accounts that are still inside the 48-hour waiting period.
"""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import (
    DEFAULT_CONTRIBUTION_MINOR,
    DEMO_PAYOUT_MINOR,
    DEMO_THRESHOLD_MM,
    MEMBER_ACTIVE,
    MEMBER_BLOCKED,
    OUTCOME_APPROVE,
    PAYOUT_SUCCESS,
    REASON_OK,
)
from .models import (
    AuditLog,
    Contribution,
    Decision,
    Event,
    Member,
    Payout,
    Policy,
    Pool,
    new_id,
    utcnow,
)
from .services.paypal import to_payout_amount

RNG = random.Random(42)

# Month-3 state from the money-flow document (before the big flood):
# 10,000 x Rs 100 x 3 months, split 70/20/10, minus paid claims and fees.
INITIAL_PAYOUT_BALANCE_MINOR = 185_600_000  # Rs 18,56,000
INITIAL_RESERVE_MINOR = 58_800_000          # Rs 5,88,000
INITIAL_RUNNING_COSTS_MINOR = 29_400_000    # Rs 2,94,000

PERSONA_ID = "mem_meena0001"
PERSONA_EMAIL = "meena.rider@example.com"
RING_PAYOUT_EMAIL = "ring-collector@example.com"

FIRST_NAMES = [
    "Meena", "Arjun", "Priya", "Ravi", "Kavya", "Suresh", "Anita", "Vikram",
    "Divya", "Rahul", "Lakshmi", "Imran", "Farhan", "Sneha", "Kiran", "Pooja",
    "Naveen", "Ayesha", "Sanjay", "Deepa", "Ramesh", "Swati", "Manoj", "Nisha",
    "Yusuf", "Bhavana", "Tarun", "Shreya", "Ganesh", "Reena", "Salman", "Neha",
    "Prakash", "Anjali", "Rajesh", "Sowmya", "Aditya", "Meghana", "Sameer", "Padma",
]
LAST_NAMES = [
    "Kumari", "Rao", "Reddy", "Sharma", "Naidu", "Yadav", "Khan", "Patel",
    "Goud", "Singh", "Verma", "Das", "Iyer", "Menon", "Chary", "Bhat",
    "Ali", "Prasad", "Murthy", "Joshi", "Kaur", "Shetty", "Nair", "Mehta",
]

ZONE_WEIGHTS = [
    ("hyderabad-central", 28),
    ("hyderabad-north", 20),
    ("hyderabad-south", 18),
    ("hyderabad-east", 12),
    ("hyderabad-west", 12),
    ("warangal", 10),
]

DEMO_SENTENCE = (
    "If heavy rain crosses 50 mm in 24 hours in my area and I cannot work, "
    "pay me 500 rupees, up to 3 days a month."
)


def _weighted_zone() -> str:
    zones = [zone for zone, _ in ZONE_WEIGHTS]
    weights = [weight for _, weight in ZONE_WEIGHTS]
    return RNG.choices(zones, weights=weights, k=1)[0]


def _iso(value) -> str:
    return value.isoformat() if value else ""


def create_demo_pool(db: Session) -> Pool:
    pool = Pool(
        id="pool_raincheck01",
        name="RainCheck Hyderabad Community Pool",
        currency="INR",
        payout_balance_minor=INITIAL_PAYOUT_BALANCE_MINOR,
        reserve_balance_minor=INITIAL_RESERVE_MINOR,
        running_costs_minor=INITIAL_RUNNING_COSTS_MINOR,
        contribution_amount_minor=DEFAULT_CONTRIBUTION_MINOR,
        paused=False,
    )
    db.add(pool)
    db.flush()
    return pool


def _member_rows(count: int, now) -> tuple[list[dict], list[dict]]:
    """Build member + policy rows. Persona and fraud ring are fixed."""
    members: list[dict] = []
    policies: list[dict] = []

    def add_member(
        *,
        member_id: str,
        name: str,
        email: str,
        paypal_email: str,
        zone: str,
        verified: bool,
        status: str,
        created_at,
        device_id: str,
        signup_ip: str,
        threshold: float = DEMO_THRESHOLD_MM,
        payout_minor: int = DEMO_PAYOUT_MINOR,
        monthly_cap: int = 3,
        source_text: str = DEMO_SENTENCE,
    ) -> None:
        members.append(
            {
                "id": member_id,
                "name": name,
                "email": email,
                "paypal_email": paypal_email,
                "phone": f"+9198{RNG.randint(10_000_000, 99_999_999)}",
                "zone": zone,
                "device_id": device_id,
                "signup_ip": signup_ip,
                "verified": verified,
                "status": status,
                "payout_email_changed_at": None,
                "created_at": created_at,
            }
        )
        policies.append(
            {
                "id": new_id("pol"),
                "member_id": member_id,
                "pool_id": "pool_raincheck01",
                "schema_version": "1.0",
                "trigger_type": "rainfall",
                "data_source": "open-meteo",
                "zone": zone,
                "metric": "precipitation_sum_mm_24h",
                "comparator": ">=",
                "threshold": threshold,
                "payout_amount_minor": payout_minor,
                "currency": "INR",
                "max_payouts_per_day": 1,
                "max_payouts_per_month": monthly_cap,
                "waiting_period_hours": 48,
                "active": status == MEMBER_ACTIVE,
                "starts_at": created_at,
                "ends_at": None,
                "source_text": source_text,
                "parser_source": "seed",
                "risk_score": 0,
                "risk_flags": "[]",
                "created_at": created_at,
            }
        )

    # --- Persona: Meena, the delivery rider from the story ------------------
    add_member(
        member_id=PERSONA_ID,
        name="Meena Kumari",
        email=PERSONA_EMAIL,
        paypal_email="meena.paypal@example.com",
        zone="hyderabad-central",
        verified=True,
        status=MEMBER_ACTIVE,
        created_at=now - timedelta(days=75),
        device_id="DEV-MEENA-01",
        signup_ip="49.207.11.24",
    )

    # --- Fraud ring: one payout address, one device, seven accounts ---------
    # Six slipped in before device-sharing checks existed, so they are active
    # and get HOLD_FOR_REVIEW at payout time. The seventh is already blocked.
    for index in range(7):
        add_member(
            member_id=f"mem_ring{index + 1:04d}",
            name=f"Ring Account {index + 1}",
            email=f"ring.account{index + 1}@example.com",
            paypal_email=RING_PAYOUT_EMAIL,
            zone="hyderabad-central",
            verified=True,
            status=MEMBER_BLOCKED if index == 6 else MEMBER_ACTIVE,
            created_at=now - timedelta(days=61),
            device_id="DEV-RING-01",
            signup_ip="203.0.113.7",
        )

    # --- Unverified accounts: must be held for human review ----------------
    for index in range(4):
        add_member(
            member_id=f"mem_unver{index + 1:04d}",
            name=f"Unverified Worker {index + 1}",
            email=f"unverified{index + 1}@example.com",
            paypal_email=f"unverified.paypal{index + 1}@example.com",
            zone="hyderabad-north",
            verified=False,
            status=MEMBER_ACTIVE,
            created_at=now - timedelta(days=40),
            device_id=f"DEV-UNVER-{index + 1:02d}",
            signup_ip=f"10.44.0.{index + 1}",
        )

    used = len(members)
    for index in range(max(0, count - used)):
        zone = _weighted_zone()
        created_at = now - timedelta(
            days=RNG.randint(5, 120), hours=RNG.randint(0, 23), minutes=RNG.randint(0, 59)
        )
        # A handful of brand-new enrollments demo the waiting period.
        if index < 5:
            created_at = now - timedelta(hours=2)
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)]
        add_member(
            member_id=f"mem_{index + 1:06d}",
            name=f"{first} {last}",
            email=f"worker{index + 1:05d}@example.com",
            paypal_email=f"worker{index + 1:05d}.paypal@example.com",
            zone=zone,
            verified=RNG.random() > 0.03,
            status=MEMBER_ACTIVE,
            created_at=created_at,
            device_id=f"DEV-{index + 1:06d}",
            signup_ip=f"10.{(index // 65536) % 250}.{(index // 256) % 250}.{index % 250}",
            threshold=RNG.choice([40.0, 50.0, 50.0, 50.0, 50.0, 60.0]),
            payout_minor=RNG.choice([40_000, 50_000, 50_000, 50_000, 50_000, 60_000]),
            monthly_cap=2 if index % 17 == 0 else 3,
        )

    return members, policies


def _seed_history(db: Session, pool: Pool, now) -> list[dict]:
    """Two past storms so the ledger and receipts are populated on first load."""
    settings = get_settings()
    events: list[dict] = []
    plans = [
        {
            "event_id": "evt_seed000001",
            "zone": "hyderabad-central",
            "value": 62.0,
            "days": 1,
            "age_days": 6,
            "count": 44,
            "include_persona": True,
        },
        {
            "event_id": "evt_seed000002",
            "zone": "hyderabad-south",
            "value": 58.0,
            "days": 2,
            "age_days": 2,
            "count": 28,
            "include_persona": False,
        },
    ]

    for plan in plans:
        created_at = now - timedelta(days=plan["age_days"], hours=3)
        event = Event(
            id=plan["event_id"],
            pool_id=pool.id,
            event_key=f"seed:{plan['zone']}:{created_at.date().isoformat()}",
            trigger_type="rainfall",
            data_source="open-meteo",
            zone=plan["zone"],
            metric="precipitation_sum_mm_24h",
            value=plan["value"],
            threshold=DEMO_THRESHOLD_MM,
            days=plan["days"],
            mode="seeded",
            status="processed",
            raw_json='{"seeded": true}',
            created_at=created_at,
            processed_at=created_at + timedelta(minutes=2),
        )
        db.add(event)
        db.flush()

        query = (
            db.query(Member, Policy)
            .join(Policy, Policy.member_id == Member.id)
            .filter(
                Member.zone == plan["zone"],
                Member.status == MEMBER_ACTIVE,
                Member.verified.is_(True),
                Member.id != PERSONA_ID,
            )
            .order_by(Member.created_at.asc())
        )
        selected = query.limit(plan["count"]).all()
        if plan["include_persona"]:
            persona = (
                db.query(Member, Policy)
                .join(Policy, Policy.member_id == Member.id)
                .filter(Member.id == PERSONA_ID)
                .first()
            )
            if persona:
                selected = [persona] + selected

        paid_minor = 0
        for member, policy in selected:
            amount = min(policy.payout_amount_minor * plan["days"], 50_000 * 3)
            decision_id = new_id("dec")
            db.add(
                Decision(
                    id=decision_id,
                    event_id=event.id,
                    policy_id=policy.id,
                    member_id=member.id,
                    outcome=OUTCOME_APPROVE,
                    reason_code=REASON_OK,
                    reason_detail=(
                        f"{plan['value']:g} mm crossed the {policy.threshold:g} mm threshold "
                        f"in {plan['zone']}; {plan['days']} day(s) approved."
                    ),
                    risk_score=0,
                    payable_days=plan["days"],
                    amount_minor=amount,
                    idempotency_key=f"decision:{event.id}:{policy.id}",
                    created_at=created_at + timedelta(minutes=2),
                )
            )
            db.add(
                Payout(
                    id=new_id("pay"),
                    decision_id=decision_id,
                    event_id=event.id,
                    policy_id=policy.id,
                    member_id=member.id,
                    amount_minor=amount,
                    currency="INR",
                    send_currency=settings.paypal_payout_currency,
                    send_amount=to_payout_amount(
                        amount, settings.paypal_payout_currency, settings.payout_inr_per_usd
                    ),
                    status=PAYOUT_SUCCESS,
                    provider="mock",
                    batch_id=f"MOCKBATCH-SEED-{plan['event_id'][-4:]}",
                    item_id=new_id("MOCKITEM"),
                    receiver=member.paypal_email,
                    idempotency_key=f"payout:{event.id}:{policy.id}",
                    attempts=1,
                    created_at=created_at + timedelta(minutes=2),
                    updated_at=created_at + timedelta(minutes=3),
                )
            )
            paid_minor += amount

        pool.payout_balance_minor -= paid_minor
        db.add(
            AuditLog(
                ts=created_at + timedelta(minutes=3),
                actor="seed",
                action="seed.event_processed",
                entity_type="event",
                entity_id=event.id,
                detail_json=(
                    '{"seeded":true,"paid_minor":%d,"note":"demo history, MOCK provider"}'
                    % paid_minor
                ),
            )
        )
        events.append({"event_id": event.id, "paid_minor": paid_minor})

    db.flush()
    return events


def seed(db: Session, member_count: int | None = None) -> dict:
    """Create the demo pool from scratch. Caller must ensure tables exist."""
    settings = get_settings()
    count = member_count or settings.seed_members
    now = utcnow()

    pool = create_demo_pool(db)
    members, policies = _member_rows(count, now)
    db.bulk_insert_mappings(Member, members)
    db.bulk_insert_mappings(Policy, policies)
    db.flush()

    history = _seed_history(db, pool, now)
    db.add(
        AuditLog(
            actor="seed",
            action="demo.seeded",
            entity_type="pool",
            entity_id=pool.id,
            detail_json='{"members":%d,"policies":%d,"history_events":%d}'
            % (len(members), len(policies), len(history)),
        )
    )
    db.commit()
    return {
        "pool_id": pool.id,
        "members": len(members),
        "policies": len(policies),
        "history": history,
    }


def seed_if_empty(db: Session) -> dict | None:
    if db.query(func.count(Pool.id)).scalar():
        return None
    return seed(db)


def reset_demo(db: Session, *, keep_members: bool = True) -> dict:
    """Clear events/decisions/payouts and restore demo balances.

    The 10,000 seeded members and policies are kept so the operator does not
    have to reseed the pool. Members and policies created during rehearsal
    (the user-enrollment demo, the sybil attempt) are removed, so the next run
    of the demo starts from the same baseline and the same emails are free.
    """
    pool = db.query(Pool).order_by(Pool.created_at.asc()).first()
    if pool is None:
        return seed(db)

    db.execute(delete(Payout))
    db.execute(delete(Decision))
    db.execute(delete(Event))
    db.execute(delete(Contribution))
    db.execute(delete(AuditLog))

    demo_member_ids = [
        row[0]
        for row in db.query(Policy.member_id)
        .filter(Policy.parser_source != "seed")
        .distinct()
        .all()
    ]
    if demo_member_ids:
        db.execute(delete(Policy).where(Policy.member_id.in_(demo_member_ids)))
        db.execute(delete(Member).where(Member.id.in_(demo_member_ids)))

    pool.payout_balance_minor = INITIAL_PAYOUT_BALANCE_MINOR
    pool.reserve_balance_minor = INITIAL_RESERVE_MINOR
    pool.running_costs_minor = INITIAL_RUNNING_COSTS_MINOR
    pool.paused = False
    pool.pause_reason = None
    pool.updated_at = utcnow()
    db.flush()

    history = _seed_history(db, pool, utcnow())
    db.add(
        AuditLog(
            actor="operator",
            action="demo.reset",
            entity_type="pool",
            entity_id=pool.id,
            detail_json='{"keep_members":%s}' % ("true" if keep_members else "false"),
        )
    )
    db.commit()
    return {
        "pool_id": pool.id,
        "reset": True,
        "members_kept": keep_members,
        "rehearsal_members_removed": len(demo_member_ids),
        "history": history,
    }


if __name__ == "__main__":  # pragma: no cover - manual tool
    import argparse

    from .db import SessionLocal, create_all

    parser = argparse.ArgumentParser(description="Seed the RainCheck demo database")
    parser.add_argument("--members", type=int, default=None)
    parser.add_argument("--fresh", action="store_true", help="delete all data first")
    args = parser.parse_args()

    create_all()
    session = SessionLocal()
    try:
        if args.fresh:
            for model in (Payout, Decision, Event, Contribution, AuditLog, Policy, Member, Pool):
                session.execute(delete(model))
            session.commit()
        result = seed(session, args.members)
        print(result)
    finally:
        session.close()
