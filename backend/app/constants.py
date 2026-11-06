"""Shared constants: zones, reason codes, policy bounds.

The policy bounds are enforced by *deterministic code*, never by the AI. The AI
may propose a policy, but anything outside these limits is clamped here and the
clamp is reported to the user.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Zones. Each zone carries coordinates so the trigger engine can poll a real
# weather feed for that exact area.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    city: str
    latitude: float
    longitude: float


ZONES: dict[str, Zone] = {
    z.id: z
    for z in [
        Zone("hyderabad-central", "Hyderabad Central", "Hyderabad", 17.3850, 78.4867),
        Zone("hyderabad-north", "Hyderabad North (Secunderabad)", "Hyderabad", 17.4948, 78.3996),
        Zone("hyderabad-south", "Hyderabad South (Charminar)", "Hyderabad", 17.3433, 78.4890),
        Zone("hyderabad-east", "Hyderabad East (Uppal)", "Hyderabad", 17.4000, 78.5700),
        Zone("hyderabad-west", "Hyderabad West (Gachibowli)", "Hyderabad", 17.4100, 78.3900),
        Zone("warangal", "Warangal", "Warangal", 17.9689, 79.5941),
    ]
}

DEFAULT_ZONE = "hyderabad-central"


def zone_name(zone_id: str) -> str:
    zone = ZONES.get(zone_id)
    return zone.name if zone else zone_id


# ---------------------------------------------------------------------------
# Policy bounds (hard limits). A policy can never exceed these, whatever the
# user typed or the model returned.
# ---------------------------------------------------------------------------

MIN_THRESHOLD_MM = 5.0
MAX_THRESHOLD_MM = 300.0
MIN_PAYOUT_MINOR = 5_000          # Rs 50
MAX_PAYOUT_MINOR = 200_000        # Rs 2,000
MIN_PAYOUTS_PER_DAY = 1
MAX_PAYOUTS_PER_DAY = 1           # one payout per member per day
MIN_PAYOUTS_PER_MONTH = 1
MAX_PAYOUTS_PER_MONTH = 3         # matches the pool's Rs 500 x 3 days design
MIN_WAITING_HOURS = 24
MAX_WAITING_HOURS = 168           # 7 days
DEFAULT_WAITING_HOURS = 48
DEFAULT_MAX_PAYOUTS_PER_MONTH = 3

SUPPORTED_TRIGGER_TYPES = {"rainfall"}
SUPPORTED_METRICS = {"precipitation_sum_mm_24h"}

# Monthly contribution per member (Rs 100).
DEFAULT_CONTRIBUTION_MINOR = 10_000

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Reason codes. Every decision carries exactly one, so the ledger is
# explainable and testable.
# ---------------------------------------------------------------------------

REASON_OK = "OK"
REASON_PARTIAL_MONTHLY_CAP = "PARTIAL_MONTHLY_CAP"
REASON_POOL_PAUSED = "POOL_PAUSED"
REASON_POLICY_INACTIVE = "POLICY_INACTIVE"
REASON_POLICY_WINDOW = "POLICY_WINDOW_CLOSED"
REASON_WAITING_PERIOD = "WAITING_PERIOD_NOT_MET"
REASON_MEMBER_BLOCKED = "MEMBER_BLOCKED"
REASON_MEMBER_UNVERIFIED = "MEMBER_NOT_VERIFIED"
REASON_ZONE_MISMATCH = "ZONE_MISMATCH"
REASON_THRESHOLD_NOT_MET = "THRESHOLD_NOT_MET"
REASON_DAILY_CAP = "DAILY_CAP_REACHED"
REASON_MONTHLY_CAP = "MONTHLY_CAP_REACHED"
REASON_POOL_INSUFFICIENT = "POOL_INSUFFICIENT_FUNDS"
REASON_DUPLICATE_EVENT = "DUPLICATE_EVENT"
REASON_HIGH_RISK = "HIGH_RISK_HOLD"
REASON_TRIGGER_MISMATCH = "TRIGGER_TYPE_MISMATCH"

# Fraud / anomaly flags raised by the screener.
FLAG_DUPLICATE_PAYOUT_DESTINATION = "DUPLICATE_PAYOUT_DESTINATION"
FLAG_DEVICE_REUSE = "DEVICE_REUSE"
FLAG_SIGNUP_VELOCITY = "SIGNUP_VELOCITY"
FLAG_UNVERIFIED_ACCOUNT = "UNVERIFIED_ACCOUNT"
FLAG_PAYOUT_DESTINATION_CHANGED = "PAYOUT_DESTINATION_CHANGED_RECENTLY"
FLAG_ZONE_UNCONFIRMED = "ZONE_UNCONFIRMED"
FLAG_AI_ADVISORY = "AI_ADVISORY"

HOLD_RISK_SCORE = 70
FLAG_RISK_SCORE = 40


# ---------------------------------------------------------------------------
# Event / decision vocabulary
# ---------------------------------------------------------------------------

OUTCOME_APPROVE = "APPROVE"
OUTCOME_DENY = "DENY"
OUTCOME_HOLD = "HOLD_FOR_REVIEW"
OUTCOMES = (OUTCOME_APPROVE, OUTCOME_DENY, OUTCOME_HOLD)

PAYOUT_CREATED = "CREATED"
PAYOUT_PENDING = "PENDING"
PAYOUT_SUCCESS = "SUCCESS"
PAYOUT_FAILED = "FAILED"
PAYOUT_HELD = "HELD"

EVENT_RECEIVED = "received"
EVENT_PROCESSED = "processed"

MEMBER_ACTIVE = "active"
MEMBER_BLOCKED = "blocked"

TRIGGER_RAINFALL = "rainfall"
METRIC_PRECIP_24H = "precipitation_sum_mm_24h"
DATA_SOURCE_OPEN_METEO = "open-meteo"

# Demo trigger threshold in mm/24h, used by the persona story and the seed data.
DEMO_THRESHOLD_MM = 50.0
DEMO_PAYOUT_MINOR = 50_000  # Rs 500


def format_inr(amount_minor: int) -> str:
    """4196000 -> 'Rs 41,960.00' (Indian digit grouping)."""
    rupees = amount_minor / 100
    whole = int(rupees)
    paise = int(round((rupees - whole) * 100))
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"Rs {s}.{paise:02d}"
