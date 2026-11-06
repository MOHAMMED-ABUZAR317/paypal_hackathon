"""Deterministic natural-language policy parser (safe baseline).

This parser is intentionally boring: regex extraction, hard bounds, explicit
failure. It runs with no API key, so `POST /api/policies/parse` always works and
the demo can never be taken down by a model outage.

The AI layer (member 3) calls this as its fallback and as the enforcement point
for bounds - the model output is never trusted for limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..constants import (
    DEFAULT_MAX_PAYOUTS_PER_MONTH,
    DEFAULT_WAITING_HOURS,
    DEFAULT_ZONE,
    MAX_PAYOUT_MINOR,
    MAX_PAYOUTS_PER_DAY,
    MAX_PAYOUTS_PER_MONTH,
    MAX_THRESHOLD_MM,
    MAX_WAITING_HOURS,
    MIN_PAYOUT_MINOR,
    MIN_THRESHOLD_MM,
    MIN_WAITING_HOURS,
    SCHEMA_VERSION,
    SUPPORTED_TRIGGER_TYPES,
    ZONES,
    zone_name,
)
from ..schemas import PolicyPreview

WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

# Word-boundary match, so the product name "RainCheck" is not mistaken for a
# rainfall trigger. Plurals and "-y" forms still count ("rains", "rainy").
RAIN_PATTERN = re.compile(
    r"\b(?:rain(?:s|fall|y)?|monsoon|precipitation|storm(?:s|y)?|downpour)\b"
)
OTHER_TRIGGERS = {
    "earthquake": "earthquake",
    "heat wave": "heat wave",
    "heatwave": "heat wave",
    "curfew": "curfew",
    "flight delay": "flight delay",
    "flood": "flood",
}

INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "jailbreak",
    "disregard the",
    "you are now",
    "developer mode",
)

ZONE_KEYWORDS = {
    "hyderabad-central": ("central", "hyderabad central", "abids", "nampally"),
    "hyderabad-north": ("north", "secunderabad", "begumpet", "paradise"),
    "hyderabad-south": ("south", "charminar", "old city", "mehdipatnam"),
    "hyderabad-east": ("east", "uppal", "lb nagar", "nacharam"),
    "hyderabad-west": ("west", "gachibowli", "madhapur", "hitech", "kondapur"),
    "warangal": ("warangal", "kazipet", "hanamkonda"),
}


@dataclass
class ParseOutcome:
    ok: bool
    policy: PolicyPreview | None = None
    error: str | None = None
    attempts: int = 1
    notes: list[str] = field(default_factory=list)


def _clamp(value: float, low: float, high: float) -> tuple[float, bool]:
    clamped = max(low, min(high, value))
    return clamped, clamped != value


def extract_zone(text: str, fallback: str) -> str:
    lowered = text.lower()
    for zone_id, keywords in ZONE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return zone_id
    return fallback if fallback in ZONES else DEFAULT_ZONE


def extract_threshold(text: str) -> float | None:
    lowered = text.lower().replace(",", "")
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?|m\.m\.)", 1.0),
        (r"(\d+(?:\.\d+)?)\s*(?:cm|centimet(?:er|re)s?)", 10.0),
        (r"(\d+(?:\.\d+)?)\s*(?:inch|inches|in)\b", 25.4),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, lowered)
        if match:
            return float(match.group(1)) * multiplier
    return None


def extract_payout_rupees(text: str) -> int | None:
    lowered = text.lower().replace(",", "")
    patterns = [
        r"(?:pay(?:\s+me)?|payout(?:\s+of)?|receive|get|give\s+me|cover\s+of)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)",
        r"(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:rupees?|rs\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return int(float(match.group(1)))
    return None


def extract_monthly_cap(text: str) -> int | None:
    lowered = text.lower()
    match = re.search(
        r"(?:max(?:imum)?|up\s*to|upto|only)?\s*"
        r"(\d+|one|two|three|four|five|six)\s*"
        r"(?:days?|payouts?|times?|claims?)\s*"
        r"(?:per|a|each|every|in\s+a)?\s*month",
        lowered,
    )
    if match:
        raw = match.group(1)
        return int(raw) if raw.isdigit() else WORD_NUMBERS.get(raw)
    frequency = {"once": 1, "twice": 2, "thrice": 3}
    for word, value in frequency.items():
        if re.search(rf"\b{word}\b\s*(?:a|per|each|every)\s*month", lowered):
            return value
    match = re.search(r"(\d+|one|two|three)\s*(?:storm|rainy)\s*days?", lowered)
    if match:
        raw = match.group(1)
        return int(raw) if raw.isdigit() else WORD_NUMBERS.get(raw)
    return None


def extract_waiting_hours(text: str) -> int | None:
    lowered = text.lower()
    match = re.search(r"(\d+)\s*(?:hours?|hrs?)", lowered)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*days?", lowered)
    if match and "wait" in lowered:
        return int(match.group(1)) * 24
    return None


def _plain_language(policy: PolicyPreview) -> str:
    rupees = policy.payout_amount_minor // 100
    return (
        f"If 24-hour rainfall in {zone_name(policy.zone)} reaches "
        f"{policy.threshold:g} mm or more, you receive Rs {rupees} for that day. "
        f"You can be paid for up to {policy.max_payouts_per_month} rainy days a month "
        f"(one payout per day). Cover starts {policy.waiting_period_hours} hours "
        f"after you join, so nobody can sign up during a storm and claim."
    )


def parse_policy_text(
    text: str,
    *,
    zone: str = DEFAULT_ZONE,
    source: str = "rules",
    attempts: int = 1,
) -> ParseOutcome:
    """Parse a sentence into a bounded PolicyPreview, or fail safely."""
    raw = (text or "").strip()
    lowered = raw.lower()
    notes: list[str] = []

    if len(raw) < 3:
        return ParseOutcome(False, error="Please describe the cover in one sentence.")

    if any(marker in lowered for marker in INJECTION_MARKERS):
        notes.append(
            "Instruction-like wording was ignored. Only the policy fields below are used."
        )

    has_rain = RAIN_PATTERN.search(lowered) is not None
    if not has_rain:
        for marker, label in OTHER_TRIGGERS.items():
            if marker in lowered:
                return ParseOutcome(
                    False,
                    error=(
                        f"'{label}' triggers are not enabled in this prototype. "
                        "RainCheck v1 supports rainfall only; the same engine can be "
                        "extended to other public data feeds."
                    ),
                    attempts=attempts,
                )
        return ParseOutcome(
            False,
            error=(
                "I could not find a rainfall trigger. Try: \"If rainfall crosses "
                "50 mm in 24 hours in Hyderabad Central, pay me Rs 500, up to 3 days a month.\""
            ),
            attempts=attempts,
        )

    threshold = extract_threshold(raw)
    if threshold is None:
        threshold = 50.0
        notes.append("No rainfall threshold found, so 50 mm/24h was used. Edit it if needed.")
    threshold, threshold_clamped = _clamp(threshold, MIN_THRESHOLD_MM, MAX_THRESHOLD_MM)
    if threshold_clamped:
        notes.append(
            f"Threshold was limited to the allowed range "
            f"{MIN_THRESHOLD_MM:g}-{MAX_THRESHOLD_MM:g} mm by the rule engine."
        )

    rupees = extract_payout_rupees(raw)
    if rupees is None:
        rupees = 500
        notes.append("No payout amount found, so Rs 500 was used. Edit it if needed.")
    payout_minor = int(rupees * 100)
    payout_minor, payout_clamped = _clamp(payout_minor, MIN_PAYOUT_MINOR, MAX_PAYOUT_MINOR)
    payout_minor = int(payout_minor)
    if payout_clamped:
        notes.append(
            f"Payout was limited to Rs {MIN_PAYOUT_MINOR // 100}-"
            f"Rs {MAX_PAYOUT_MINOR // 100} by the rule engine."
        )

    monthly = extract_monthly_cap(raw) or DEFAULT_MAX_PAYOUTS_PER_MONTH
    monthly, monthly_clamped = _clamp(monthly, 1, MAX_PAYOUTS_PER_MONTH)
    monthly = int(monthly)
    if monthly_clamped:
        notes.append(f"Monthly cap was limited to {MAX_PAYOUTS_PER_MONTH} days.")

    waiting = extract_waiting_hours(raw) or DEFAULT_WAITING_HOURS
    waiting, waiting_clamped = _clamp(waiting, MIN_WAITING_HOURS, MAX_WAITING_HOURS)
    waiting = int(waiting)
    if waiting_clamped:
        notes.append(
            f"Waiting period was limited to {MIN_WAITING_HOURS}-{MAX_WAITING_HOURS} hours."
        )

    policy = PolicyPreview(
        trigger_type="rainfall",
        data_source="open-meteo",
        zone=extract_zone(raw, zone),
        metric="precipitation_sum_mm_24h",
        operator=">=",
        threshold=round(float(threshold), 1),
        payout_amount_minor=payout_minor,
        currency="INR",
        max_payouts_per_day=MAX_PAYOUTS_PER_DAY,
        max_payouts_per_month=monthly,
        waiting_period_hours=waiting,
        source="rules" if source == "rules" else source,  # type: ignore[arg-type]
        warnings=notes,
        confidence=0.55 if notes else 0.8,
    )
    policy.plain_language = _plain_language(policy)
    if policy.trigger_type not in SUPPORTED_TRIGGER_TYPES:
        return ParseOutcome(False, error="Unsupported trigger type.", attempts=attempts)
    return ParseOutcome(True, policy=policy, attempts=attempts, notes=notes)


def enforce_bounds(policy: PolicyPreview, *, source: str | None = None) -> PolicyPreview:
    """Re-clamp a policy that came from the client or an LLM.

    This is the server-side trust boundary: even if a browser or a model returns
    an absurd payout, this function is what the database sees.
    """
    notes = list(policy.warnings)

    def _note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    if policy.trigger_type not in SUPPORTED_TRIGGER_TYPES:
        raise ValueError(f"Unsupported trigger_type '{policy.trigger_type}'")
    if policy.operator not in {">=", ">"}:
        _note("Only '>=' comparisons are supported; the operator was set to '>='.")
        policy.operator = ">="

    threshold, clamped = _clamp(float(policy.threshold), MIN_THRESHOLD_MM, MAX_THRESHOLD_MM)
    if clamped:
        _note(
            f"Threshold clamped to {MIN_THRESHOLD_MM:g}-{MAX_THRESHOLD_MM:g} mm "
            "by the rule engine."
        )
    policy.threshold = round(float(threshold), 1)

    payout, clamped = _clamp(
        int(policy.payout_amount_minor), MIN_PAYOUT_MINOR, MAX_PAYOUT_MINOR
    )
    if clamped:
        _note(
            f"Payout clamped to Rs {MIN_PAYOUT_MINOR // 100}-Rs {MAX_PAYOUT_MINOR // 100} "
            "by the rule engine."
        )
    policy.payout_amount_minor = int(payout)

    policy.max_payouts_per_day = MAX_PAYOUTS_PER_DAY
    monthly, clamped = _clamp(int(policy.max_payouts_per_month), 1, MAX_PAYOUTS_PER_MONTH)
    if clamped:
        _note(f"Monthly cap clamped to {MAX_PAYOUTS_PER_MONTH} days.")
    policy.max_payouts_per_month = int(monthly)

    waiting, clamped = _clamp(
        int(policy.waiting_period_hours), MIN_WAITING_HOURS, MAX_WAITING_HOURS
    )
    if clamped:
        _note(
            f"Waiting period clamped to {MIN_WAITING_HOURS}-{MAX_WAITING_HOURS} hours."
        )
    policy.waiting_period_hours = int(waiting)

    policy.metric = "precipitation_sum_mm_24h"
    policy.data_source = "open-meteo"
    policy.currency = "INR"
    policy.schema_version = SCHEMA_VERSION
    if source:
        policy.source = source  # type: ignore[assignment]
    policy.warnings = notes
    policy.plain_language = _plain_language(policy)
    return policy

