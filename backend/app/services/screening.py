"""Deterministic fraud screening (rules first, AI advisory second).

The screener produces an advisory score and human-readable flags. It never
approves or blocks a payment by itself: `rules.py` owns the hard checks, and an
operator can always inspect the flags. The score is used in two places:

* enrollment - a high score blocks the enrollment outright (duplicate payout
  destination is a hard block);
* payout time - a high score turns an otherwise valid payout into
  HOLD_FOR_REVIEW.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import (
    FLAG_DEVICE_REUSE,
    FLAG_DUPLICATE_PAYOUT_DESTINATION,
    FLAG_PAYOUT_DESTINATION_CHANGED,
    FLAG_SIGNUP_VELOCITY,
    FLAG_UNVERIFIED_ACCOUNT,
    FLAG_ZONE_UNCONFIRMED,
    HOLD_RISK_SCORE,
)
from ..models import Member


@dataclass
class FraudFlag:
    code: str
    detail: str
    weight: int


@dataclass
class ScreenResult:
    score: int
    flags: list[FraudFlag] = field(default_factory=list)
    recommendation: str = "allow"  # allow | review | block

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "recommendation": self.recommendation,
            "flags": [
                {"code": f.code, "detail": f.detail, "weight": f.weight} for f in self.flags
            ],
            "explanation": self.explanation(),
        }

    def explanation(self) -> str:
        if not self.flags:
            return "No fraud signals found for this member."
        reasons = "; ".join(f.detail for f in self.flags)
        return f"{len(self.flags)} signal(s) found (score {self.score}/100): {reasons}"


def _recommend(score: int) -> str:
    if score >= HOLD_RISK_SCORE:
        return "block"
    if score >= 40:
        return "review"
    return "allow"


def screen_member(
    db: Session,
    *,
    member_id: str | None,
    paypal_email: str,
    device_id: str | None,
    signup_ip: str | None,
    zone: str,
    verified: bool,
    payout_email_changed_at: datetime | None = None,
    now: datetime | None = None,
) -> ScreenResult:
    """Score an enrollment or an existing member. Advisory only."""
    now = now or datetime.now(timezone.utc)
    flags: list[FraudFlag] = []

    shared_payout = (
        db.query(func.count(Member.id))
        .filter(
            func.lower(Member.paypal_email) == paypal_email.lower(),
            Member.id != (member_id or ""),
        )
        .scalar()
        or 0
    )
    if shared_payout:
        flags.append(
            FraudFlag(
                FLAG_DUPLICATE_PAYOUT_DESTINATION,
                f"This PayPal payout address is already used by {shared_payout} other member(s).",
                70,
            )
        )

    if device_id:
        shared_device = (
            db.query(func.count(Member.id))
            .filter(Member.device_id == device_id, Member.id != (member_id or ""))
            .scalar()
            or 0
        )
        if shared_device:
            flags.append(
                FraudFlag(
                    FLAG_DEVICE_REUSE,
                    f"Same device fingerprint as {shared_device} other member(s).",
                    25,
                )
            )

    if signup_ip:
        window_start = now - timedelta(hours=24)
        recent = (
            db.query(func.count(Member.id))
            .filter(Member.signup_ip == signup_ip, Member.created_at >= window_start)
            .scalar()
            or 0
        )
        if recent >= 3:
            flags.append(
                FraudFlag(
                    FLAG_SIGNUP_VELOCITY,
                    f"{recent} enrollments from this IP in the last 24 hours.",
                    30,
                )
            )

    if not verified:
        flags.append(
            FraudFlag(
                FLAG_UNVERIFIED_ACCOUNT,
                "PayPal account or phone is not verified.",
                20,
            )
        )

    if payout_email_changed_at is not None:
        reference = payout_email_changed_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if now - reference < timedelta(hours=72):
            flags.append(
                FraudFlag(
                    FLAG_PAYOUT_DESTINATION_CHANGED,
                    "Payout destination changed in the last 72 hours (cooling-off needed).",
                    30,
                )
            )

    if not zone:
        flags.append(FraudFlag(FLAG_ZONE_UNCONFIRMED, "No enrolled zone on file.", 15))

    score = min(100, sum(flag.weight for flag in flags))
    return ScreenResult(score=score, flags=flags, recommendation=_recommend(score))


def screen_existing_member(db: Session, member: Member, now: datetime | None = None) -> ScreenResult:
    return screen_member(
        db,
        member_id=member.id,
        paypal_email=member.paypal_email,
        device_id=member.device_id,
        signup_ip=member.signup_ip,
        zone=member.zone,
        verified=member.verified,
        payout_email_changed_at=member.payout_email_changed_at,
        now=now,
    )


def bulk_screen(db: Session, members: list[Member]) -> dict[str, ScreenResult]:
    """Screen an event's candidate members with a bounded number of queries.

    Naive per-member queries would be O(n) round-trips for a 1,700-member zone,
    so we aggregate the shared-attribute counts once and then score in memory.
    """
    if not members:
        return {}

    payout_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    ip_counts: dict[str, int] = {}

    for email, count in (
        db.query(func.lower(Member.paypal_email), func.count(Member.id))
        .filter(func.lower(Member.paypal_email).in_(
            {m.paypal_email.lower() for m in members}
        ))
        .group_by(func.lower(Member.paypal_email))
        .all()
    ):
        payout_counts[email] = count

    devices = {m.device_id for m in members if m.device_id}
    if devices:
        for device, count in (
            db.query(Member.device_id, func.count(Member.id))
            .filter(Member.device_id.in_(devices))
            .group_by(Member.device_id)
            .all()
        ):
            device_counts[device] = count

    ips = {m.signup_ip for m in members if m.signup_ip}
    if ips:
        for ip, count in (
            db.query(Member.signup_ip, func.count(Member.id))
            .filter(Member.signup_ip.in_(ips))
            .group_by(Member.signup_ip)
            .all()
        ):
            ip_counts[ip] = count

    now = datetime.now(timezone.utc)
    results: dict[str, ScreenResult] = {}
    for member in members:
        flags: list[FraudFlag] = []
        shared_payout = payout_counts.get(member.paypal_email.lower(), 0) - 1
        if shared_payout > 0:
            flags.append(
                FraudFlag(
                    FLAG_DUPLICATE_PAYOUT_DESTINATION,
                    f"This payout address is shared with {shared_payout} other member(s).",
                    70,
                )
            )
        shared_device = device_counts.get(member.device_id or "", 0) - 1
        if member.device_id and shared_device > 0:
            flags.append(
                FraudFlag(
                    FLAG_DEVICE_REUSE,
                    f"Same device fingerprint as {shared_device} other member(s).",
                    25,
                )
            )
        if member.signup_ip and ip_counts.get(member.signup_ip, 0) >= 3:
            flags.append(
                FraudFlag(
                    FLAG_SIGNUP_VELOCITY,
                    f"{ip_counts[member.signup_ip]} enrollments share this IP.",
                    30,
                )
            )
        if not member.verified:
            flags.append(
                FraudFlag(FLAG_UNVERIFIED_ACCOUNT, "PayPal account is not verified.", 20)
            )
        if member.payout_email_changed_at is not None:
            changed = member.payout_email_changed_at
            if changed.tzinfo is None:
                changed = changed.replace(tzinfo=timezone.utc)
            if now - changed < timedelta(hours=72):
                flags.append(
                    FraudFlag(
                        FLAG_PAYOUT_DESTINATION_CHANGED,
                        "Payout destination changed in the last 72 hours.",
                        30,
                    )
                )
        if not member.zone:
            flags.append(FraudFlag(FLAG_ZONE_UNCONFIRMED, "No enrolled zone on file.", 15))

        score = min(100, sum(f.weight for f in flags))
        results[member.id] = ScreenResult(score=score, flags=flags, recommendation=_recommend(score))
    return results
