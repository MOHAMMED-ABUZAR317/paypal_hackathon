"""Facade for the four AI jobs, with deterministic fallbacks everywhere.

Nothing in this module can move money. It only:
  * proposes a policy (validated + clamped by the rule engine),
  * writes advisory fraud notes,
  * explains pool health,
  * rewrites an existing receipt without changing its numbers.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...config import get_settings
from ...constants import OUTCOME_APPROVE, format_inr, zone_name
from ...models import Decision, Event, Member, Payout, Policy, Pool
from .. import screening
from ..forecast import pool_forecast
from ..receipts import payout_receipt
from .llm import LLMError, complete_json
from .parser import AIParseResult, parse_policy
from .prompts import (
    FORECAST_SYSTEM,
    RECEIPT_SYSTEM,
    SCREENER_SYSTEM,
    forecast_user_prompt,
    receipt_user_prompt,
    screener_user_prompt,
)

logger = logging.getLogger("raincheck.ai.service")

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "te": "Telugu"}


def ai_status() -> dict:
    settings = get_settings()
    return {
        "enabled": settings.ai_configured,
        "mode": "llm" if settings.ai_configured else "rules",
        "provider": "openai-compatible" if settings.ai_configured else "deterministic",
        "model": settings.ai_model if settings.ai_configured else "deterministic-fallback",
        "jobs": [
            "policy parser (structured, bounded)",
            "anomaly advisory",
            "pool forecast narrative",
            "receipt translation",
        ],
        "can_move_money": False,
        "note": (
            "AI proposes and explains. Deterministic rules authorise every payout."
            if settings.ai_configured
            else "No AI key set: all four jobs run on deterministic fallbacks. The demo still works."
        ),
    }


def _numbers(text: str) -> set[float]:
    values: set[float] = set()
    for match in _NUMBER.finditer(text or ""):
        try:
            values.add(round(float(match.group().replace(",", "")), 2))
        except ValueError:
            continue
    return values


def numbers_preserved(original: str, rewritten: str) -> bool:
    """Numeric guard: a rewrite may not drop or change any number."""
    if not rewritten or not rewritten.strip():
        return False
    required = _numbers(original)
    produced = _numbers(rewritten)
    return required.issubset(produced)


async def _advisory(system: str, user: str) -> tuple[dict | None, str | None]:
    try:
        result = await complete_json(system=system, user=user, max_tokens=500)
        return result.data, None
    except LLMError as exc:
        logger.warning("AI advisory unavailable: %s", exc)
        return None, str(exc)


# ---------------------------------------------------------------------------
# 1. Policy parsing
# ---------------------------------------------------------------------------


async def parse_policy_text(text: str, zone: str) -> AIParseResult:
    return await parse_policy(text, zone)


# ---------------------------------------------------------------------------
# 2. Anomaly advisory (member)
# ---------------------------------------------------------------------------


async def review_member(db: Session, member: Member) -> dict:
    deterministic = screening.screen_existing_member(db, member)
    shared_payouts = (
        db.query(func.count(Member.id))
        .filter(
            func.lower(Member.paypal_email) == member.paypal_email.lower(),
            Member.id != member.id,
        )
        .scalar()
        or 0
    )
    age_days = None
    if member.created_at:
        created = member.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days

    facts = {
        "account_age_days": age_days,
        "verified": member.verified,
        "zone": member.zone,
        "shared_payout_addresses": shared_payouts,
        "shared_device_accounts": max(
            0,
            int(
                db.query(func.count(Member.id))
                .filter(Member.device_id == member.device_id, Member.id != member.id)
                .scalar()
                or 0
            ),
        ),
        "deterministic_score": deterministic.score,
        "deterministic_flags": [f.code for f in deterministic.flags],
        "deterministic_recommendation": deterministic.recommendation,
    }
    ai, error = await _advisory(SCREENER_SYSTEM, screener_user_prompt(facts))
    fallback = {
        "risk_level": "high"
        if deterministic.score >= 70
        else "medium"
        if deterministic.score >= 40
        else "low",
        "summary": deterministic.explanation(),
        "recommendation": deterministic.recommendation,
    }
    return {
        "member_id": member.id,
        "member_name": member.name,
        "deterministic": deterministic.as_dict(),
        "ai": ai if ai else fallback,
        "source": "llm" if ai else "rules",
        "ai_error": error,
        "decision_authority": "rule engine + human operator; AI is advisory only",
    }


# ---------------------------------------------------------------------------
# 3. Anomaly advisory (event)
# ---------------------------------------------------------------------------


async def review_event(db: Session, event: Event) -> dict:
    rows = (
        db.query(Decision.outcome, func.count(Decision.id))
        .filter(Decision.event_id == event.id)
        .group_by(Decision.outcome)
        .all()
    )
    counts = {outcome: count for outcome, count in rows}
    reason_rows = (
        db.query(Decision.reason_code, func.count(Decision.id))
        .filter(Decision.event_id == event.id)
        .group_by(Decision.reason_code)
        .order_by(func.count(Decision.id).desc())
        .limit(6)
        .all()
    )
    shared = (
        db.query(Payout.receiver, func.count(Payout.id))
        .filter(Payout.event_id == event.id)
        .group_by(Payout.receiver)
        .having(func.count(Payout.id) > 1)
        .count()
    )
    avg_risk = (
        db.query(func.avg(Decision.risk_score)).filter(Decision.event_id == event.id).scalar()
        or 0
    )
    paid = (
        db.query(func.coalesce(func.sum(Payout.amount_minor), 0))
        .filter(Payout.event_id == event.id)
        .scalar()
        or 0
    )
    facts = {
        "zone": event.zone,
        "rainfall_mm": event.value,
        "days": event.days,
        "mode": event.mode,
        "counts": counts,
        "top_reasons": {code: count for code, count in reason_rows},
        "shared_payout_addresses_in_payouts": int(shared),
        "average_risk_score": round(float(avg_risk), 1),
        "total_paid_rupees": paid / 100,
    }
    ai, error = await _advisory(SCREENER_SYSTEM, screener_user_prompt(facts))
    held = counts.get("HOLD_FOR_REVIEW", 0)
    fallback = {
        "risk_level": "high" if held else "low",
        "summary": (
            f"{counts.get('APPROVE', 0):,} approved, {held:,} held for review, "
            f"{counts.get('DENY', 0):,} denied. Average risk score "
            f"{facts['average_risk_score']}/100."
        ),
        "recommendation": "review" if held else "allow",
    }
    return {
        "event_id": event.id,
        "event": {
            "zone": event.zone,
            "rainfall_mm": event.value,
            "days": event.days,
            "mode": event.mode,
        },
        "facts": facts,
        "ai": ai if ai else fallback,
        "source": "llm" if ai else "rules",
        "ai_error": error,
        "decision_authority": "rule engine; the AI only explains the pattern",
    }


# ---------------------------------------------------------------------------
# 4. Pool forecast narrative
# ---------------------------------------------------------------------------


async def forecast_insight(db: Session, pool: Pool) -> dict:
    forecast = pool_forecast(db, pool)
    facts = {
        "payout_box_rupees": pool.payout_balance_minor / 100,
        "reserve_rupees": pool.reserve_balance_minor / 100,
        "total_rupees": pool.total_balance_minor / 100,
        "active_members": forecast["active_policies"],
        "biggest_zone_members": forecast["biggest_zone"],
        "assumed_affected_members": forecast["assumed_affected_members"],
        "expected_event_cost_rupees": forecast["expected_event_cost_minor"] / 100,
        "events_covered": forecast["events_covered"],
        "monthly_inflow_rupees": forecast["monthly_inflow_minor"] / 100,
        "paused": pool.paused,
    }
    ai, error = await _advisory(FORECAST_SYSTEM, forecast_user_prompt(facts))
    covered = forecast["events_covered"]
    fallback = {
        "summary": forecast["narrative"],
        "action": (
            "Pause payouts and top up the reserve."
            if covered < 1
            else "Raise contributions or widen the contributor base before the next storm season."
            if covered < 3
            else "Cover looks healthy; keep the reserve untouched and re-check after each event."
        ),
    }
    return {
        "pool_id": pool.id,
        "facts": facts,
        "ai": ai if ai else fallback,
        "source": "llm" if ai else "rules",
        "ai_error": error,
        "note": "Assumption-based projection, not a guarantee.",
    }


# ---------------------------------------------------------------------------
# 5. Receipt writer / translator
# ---------------------------------------------------------------------------


def _load_receipt_context(db: Session, payout_id: str):
    return (
        db.query(Payout, Decision, Event, Policy, Member)
        .join(Decision, Payout.decision_id == Decision.id)
        .join(Event, Payout.event_id == Event.id)
        .join(Policy, Payout.policy_id == Policy.id)
        .join(Member, Payout.member_id == Member.id)
        .filter(Payout.id == payout_id)
        .first()
    )


async def explain_receipt(db: Session, payout_id: str, language: str = "en") -> dict:
    language = (language or "en").lower()
    if language not in SUPPORTED_LANGUAGES:
        language = "en"

    row = _load_receipt_context(db, payout_id)
    if row is None:
        raise ValueError("Payout not found")
    payout, decision, event, policy, member = row

    original = payout_receipt(
        name=member.name,
        outcome=decision.outcome,
        reason_code=decision.reason_code,
        reason_detail=decision.reason_detail,
        amount_minor=payout.amount_minor,
        payable_days=decision.payable_days,
        zone=event.zone,
        rainfall_mm=event.value,
        threshold=policy.threshold,
        status=payout.status,
        provider=payout.provider,
        send_amount=payout.send_amount,
        send_currency=payout.send_currency,
    )

    if language == "en" or not get_settings().ai_configured:
        return {
            "payout_id": payout.id,
            "language": language,
            "text": original,
            "source": "rules",
            "guard": "not_required",
            "note": (
                "English receipts are generated deterministically."
                if language == "en"
                else "No AI key configured; showing the English original."
            ),
        }

    facts = {
        "amount_rupees": payout.amount_minor / 100,
        "rainfall_mm": event.value,
        "threshold_mm": policy.threshold,
        "days": decision.payable_days,
        "mock": payout.provider == "mock",
    }
    ai, error = await _advisory(
        RECEIPT_SYSTEM, receipt_user_prompt(original, SUPPORTED_LANGUAGES[language], facts)
    )
    candidate = (ai or {}).get("text") if ai else None
    if candidate and numbers_preserved(original, candidate):
        return {
            "payout_id": payout.id,
            "language": language,
            "text": candidate,
            "source": "llm",
            "guard": "passed",
            "note": "Numbers verified against the ledger before display.",
        }
    return {
        "payout_id": payout.id,
        "language": language,
        "text": original,
        "source": "rules",
        "guard": "rejected_numeric_mismatch" if candidate else "ai_unavailable",
        "ai_error": error,
        "note": "The rewrite changed or dropped a number, so it was discarded. Safety over fluency.",
    }
