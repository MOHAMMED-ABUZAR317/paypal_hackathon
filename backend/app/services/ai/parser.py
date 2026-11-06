"""LLM policy parser with strict validation, one retry, and a safe fallback.

The model output is treated like any other untrusted input:

1. normalise aliases (`payout_amount_rupees` -> minor units, etc.);
2. validate with Pydantic (`PolicyPreview`);
3. clamp with `enforce_bounds` (server-side, authoritative);
4. only then hand the proposal to the confirmation screen.

If anything fails twice, the deterministic parser answers instead. The user is
told which source produced the rule (`source: llm | rules`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from ...config import get_settings
from ...constants import DEFAULT_ZONE, ZONES, zone_name
from ...schemas import PolicyPreview
from ..policy_parser import enforce_bounds, parse_policy_text
from .llm import LLMError, complete_json
from .prompts import POLICY_SYSTEM, policy_user_prompt

logger = logging.getLogger("raincheck.ai.parser")

MAX_ATTEMPTS = 2  # initial call + exactly one retry, as specified


@dataclass
class AIParseResult:
    ok: bool
    policy: PolicyPreview | None = None
    error: str | None = None
    attempts: int = 1
    source: str = "rules"
    notes: list[str] = field(default_factory=list)


_FIRST_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _number(value, default: float) -> float:
    """Tolerate model formatting such as "62 mm", "Rs 1,200" or "3 days"."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("₹", "").strip()
        match = _FIRST_NUMBER.search(cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return default
    return default


def normalise_zone(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    lowered = value.strip().lower()
    if lowered in ZONES:
        return lowered
    for zone_id, zone in ZONES.items():
        if zone.name.lower() == lowered or zone.city.lower() == lowered:
            return zone_id
        short = zone.name.split("(")[0].strip().lower()
        if short and short in lowered:
            return zone_id
    return fallback if fallback in ZONES else DEFAULT_ZONE


def normalise_payload(data: dict, fallback_zone: str) -> dict:
    """Map plausible model aliases onto the frozen schema keys."""
    out: dict = {
        "trigger_type": "rainfall",
        "data_source": "open-meteo",
        "metric": "precipitation_sum_mm_24h",
        "operator": ">=",
        "currency": "INR",
    }
    out["zone"] = normalise_zone(
        data.get("zone") or data.get("location") or data.get("area"), fallback_zone
    )

    threshold = data.get("threshold")
    if threshold is None:
        threshold = data.get("threshold_mm") or data.get("rainfall_mm") or data.get("mm")
    out["threshold"] = _number(threshold, 50.0)

    payout = data.get("payout_amount_minor")
    if payout is None:
        rupees = (
            data.get("payout_amount_rupees")
            or data.get("payout_rupees")
            or data.get("amount_rupees")
            or data.get("amount")
        )
        payout = _number(rupees, 500.0) * 100
    out["payout_amount_minor"] = int(_number(payout, 50_000))

    monthly = (
        data.get("max_payouts_per_month")
        or data.get("max_days_per_month")
        or data.get("days_per_month")
        or data.get("monthly_cap")
    )
    out["max_payouts_per_month"] = int(_number(monthly, 3))

    waiting = (
        data.get("waiting_period_hours")
        or data.get("waiting_hours")
        or data.get("waiting_period")
    )
    out["waiting_period_hours"] = int(_number(waiting, 48))

    confidence = _number(data.get("confidence"), 0.75)
    out["confidence"] = max(0.0, min(1.0, confidence))
    out["plain_language"] = str(data.get("plain_language") or "")[:600]
    out["source"] = "llm"
    out["warnings"] = []
    return out


def _policy_from_payload(data: dict, fallback_zone: str) -> PolicyPreview:
    normalised = normalise_payload(data, fallback_zone)
    policy = PolicyPreview.model_validate(normalised)
    policy = enforce_bounds(policy, source="llm")
    if not policy.plain_language:
        policy.plain_language = (
            f"If 24-hour rainfall in {zone_name(policy.zone)} reaches "
            f"{policy.threshold:g} mm, you receive Rs {policy.payout_amount_minor // 100} "
            f"for that day, up to {policy.max_payouts_per_month} days a month."
        )
    return policy


async def parse_policy(text: str, zone: str = DEFAULT_ZONE) -> AIParseResult:
    settings = get_settings()
    fallback_zone = zone if zone in ZONES else DEFAULT_ZONE

    if not settings.ai_configured:
        baseline = parse_policy_text(text, zone=fallback_zone)
        return AIParseResult(
            ok=baseline.ok,
            policy=baseline.policy,
            error=baseline.error,
            attempts=1,
            source="rules",
            notes=baseline.notes,
        )

    last_error = "AI parser failed"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await complete_json(
                system=POLICY_SYSTEM,
                user=policy_user_prompt(text, fallback_zone),
            )
            data = result.data
            if data.get("supported") is False or "error" in data:
                return AIParseResult(
                    ok=False,
                    error=str(data.get("error") or "That trigger is not supported."),
                    attempts=attempt,
                    source="llm",
                )
            policy = _policy_from_payload(data, fallback_zone)
            logger.info(
                "AI policy parsed in %sms (model=%s, attempt=%s)",
                result.latency_ms,
                result.model,
                attempt,
            )
            return AIParseResult(
                ok=True,
                policy=policy,
                attempts=attempt,
                source="llm",
                notes=[f"Structured by {result.model} and limited by the rule engine."],
            )
        except (LLMError, ValidationError, ValueError, TypeError) as exc:
            last_error = str(exc)
            logger.warning("AI parse attempt %s failed: %s", attempt, last_error)

    baseline = parse_policy_text(text, zone=fallback_zone)
    if baseline.ok and baseline.policy is not None:
        baseline.policy.warnings.append(
            "The AI parser was unavailable, so the built-in parser produced this rule. "
            "Check the fields before confirming."
        )
        return AIParseResult(
            ok=True,
            policy=baseline.policy,
            attempts=MAX_ATTEMPTS,
            source="rules",
            notes=[
                "AI unavailable or returned invalid data; deterministic parser used.",
                *baseline.notes,
            ],
        )
    return AIParseResult(
        ok=False,
        error=baseline.error or last_error,
        attempts=MAX_ATTEMPTS,
        source="rules",
    )
