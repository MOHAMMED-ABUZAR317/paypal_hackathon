"""The rule engine: deterministic code, no AI, fully unit-tested.

Inputs are plain values, outputs are a single outcome plus a reason code. This
module is the *only* thing that can authorise money movement. The AI layer
cannot import it to bypass it, and it cannot call PayPal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..constants import (
    MAX_PAYOUTS_PER_DAY,
    OUTCOME_APPROVE,
    OUTCOME_DENY,
    OUTCOME_HOLD,
    REASON_DAILY_CAP,
    REASON_DUPLICATE_EVENT,
    REASON_HIGH_RISK,
    REASON_MEMBER_BLOCKED,
    REASON_MEMBER_UNVERIFIED,
    REASON_MONTHLY_CAP,
    REASON_OK,
    REASON_PARTIAL_MONTHLY_CAP,
    REASON_POLICY_INACTIVE,
    REASON_POLICY_WINDOW,
    REASON_POOL_INSUFFICIENT,
    REASON_POOL_PAUSED,
    REASON_THRESHOLD_NOT_MET,
    REASON_TRIGGER_MISMATCH,
    REASON_WAITING_PERIOD,
    REASON_ZONE_MISMATCH,
    HOLD_RISK_SCORE,
)
from ..models import Event, Member, Policy, Pool, utcnow


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise everything to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class RuleResult:
    outcome: str
    reason_code: str
    reason_detail: str
    payable_days: int = 0
    amount_minor: int = 0

    @property
    def approved(self) -> bool:
        return self.outcome == OUTCOME_APPROVE


def evaluate(
    *,
    policy: Policy,
    member: Member,
    event: Event,
    pool: Pool,
    risk_score: int = 0,
    days_used_this_month: int = 0,
    payouts_today: int = 0,
    duplicate_decision: bool = False,
    now: datetime | None = None,
) -> RuleResult:
    """Apply every hard guard in a fixed, explainable order."""
    now = as_utc(now or utcnow())
    starts_at = as_utc(policy.starts_at) or now
    ends_at = as_utc(policy.ends_at)

    # 1. Operator emergency stop wins over everything.
    if pool.paused:
        return RuleResult(
            OUTCOME_DENY,
            REASON_POOL_PAUSED,
            f"Payouts are paused by the pool operator: {pool.pause_reason or 'no reason given'}.",
        )

    # 2. Policy state and window.
    if not policy.active:
        return RuleResult(
            OUTCOME_DENY, REASON_POLICY_INACTIVE, "This policy is not active."
        )
    if now < starts_at:
        return RuleResult(
            OUTCOME_DENY,
            REASON_POLICY_WINDOW,
            "The policy has not started yet.",
        )
    if ends_at and now > ends_at:
        return RuleResult(
            OUTCOME_DENY,
            REASON_POLICY_WINDOW,
            f"The policy ended on {ends_at.date().isoformat()}.",
        )

    # 3. Waiting period - defeats joining just before a known storm.
    eligible_at = starts_at + timedelta(hours=policy.waiting_period_hours)
    if now < eligible_at:
        remaining_hours = max(1, int((eligible_at - now).total_seconds() // 3600))
        return RuleResult(
            OUTCOME_DENY,
            REASON_WAITING_PERIOD,
            f"Waiting period not met: eligible in about {remaining_hours} hour(s).",
        )

    # 4. Trigger / area match.
    if event.trigger_type != policy.trigger_type:
        return RuleResult(
            OUTCOME_DENY,
            REASON_TRIGGER_MISMATCH,
            f"Event trigger '{event.trigger_type}' does not match policy '{policy.trigger_type}'.",
        )
    if event.zone != policy.zone:
        return RuleResult(
            OUTCOME_DENY,
            REASON_ZONE_MISMATCH,
            f"The event is in {event.zone}, but the policy covers {policy.zone}.",
        )

    # 5. Member standing.
    if member.status != "active":
        return RuleResult(
            OUTCOME_DENY, REASON_MEMBER_BLOCKED, "This member account is blocked."
        )
    if not member.verified:
        return RuleResult(
            OUTCOME_HOLD,
            REASON_MEMBER_UNVERIFIED,
            "PayPal account is not verified; a human must review before paying.",
        )

    # 6. The measurement itself.
    if event.value < policy.threshold:
        return RuleResult(
            OUTCOME_DENY,
            REASON_THRESHOLD_NOT_MET,
            f"{event.value:g} mm is below the {policy.threshold:g} mm threshold.",
        )

    # 7. Idempotency and caps.
    if duplicate_decision:
        return RuleResult(
            OUTCOME_DENY,
            REASON_DUPLICATE_EVENT,
            "This event has already been paid for this policy (idempotency guard).",
        )
    if payouts_today >= min(policy.max_payouts_per_day, MAX_PAYOUTS_PER_DAY):
        return RuleResult(
            OUTCOME_DENY,
            REASON_DAILY_CAP,
            f"Daily cap reached ({payouts_today} payout(s) today).",
        )

    days_remaining = policy.max_payouts_per_month - days_used_this_month
    if days_remaining <= 0:
        return RuleResult(
            OUTCOME_DENY,
            REASON_MONTHLY_CAP,
            f"Monthly cap reached ({policy.max_payouts_per_month} days already paid).",
        )

    payable_days = max(1, min(event.days, days_remaining))
    amount_minor = policy.payout_amount_minor * payable_days

    # 8. Affordability - payout box first, reserve as the backstop.
    if pool.total_balance_minor < amount_minor:
        return RuleResult(
            OUTCOME_HOLD,
            REASON_POOL_INSUFFICIENT,
            (
                f"Pool has Rs {pool.total_balance_minor / 100:,.2f} but this payout needs "
                f"Rs {amount_minor / 100:,.2f}; held for review instead of paying partially."
            ),
        )

    # 9. Advisory risk score - never a silent denial, always a human hold.
    if risk_score >= HOLD_RISK_SCORE:
        return RuleResult(
            OUTCOME_HOLD,
            REASON_HIGH_RISK,
            f"Fraud screener scored this member {risk_score}/100; human review required.",
            payable_days,
            amount_minor,
        )

    if payable_days < event.days:
        return RuleResult(
            OUTCOME_APPROVE,
            REASON_PARTIAL_MONTHLY_CAP,
            (
                f"Approved for {payable_days} of {event.days} day(s): the monthly cap of "
                f"{policy.max_payouts_per_month} days limits the rest."
            ),
            payable_days,
            amount_minor,
        )

    return RuleResult(
        OUTCOME_APPROVE,
        REASON_OK,
        (
            f"{event.value:g} mm crossed the {policy.threshold:g} mm threshold in "
            f"{event.zone}; {payable_days} day(s) approved."
        ),
        payable_days,
        amount_minor,
    )
