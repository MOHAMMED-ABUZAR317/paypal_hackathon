"""Unit tests for the deterministic rule engine (member 2).

These are the most important tests in the project: they prove that money can
only move when every hard guard passes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.constants import (
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
    REASON_WAITING_PERIOD,
    REASON_ZONE_MISMATCH,
)
from app.models import Event, Member, Policy, Pool, utcnow
from app.services.rules import evaluate


def make_policy(**overrides) -> Policy:
    now = utcnow()
    base = dict(
        id="pol_1",
        member_id="mem_1",
        pool_id="pool_1",
        trigger_type="rainfall",
        data_source="open-meteo",
        zone="hyderabad-central",
        metric="precipitation_sum_mm_24h",
        comparator=">=",
        threshold=50.0,
        payout_amount_minor=50_000,
        currency="INR",
        max_payouts_per_day=1,
        max_payouts_per_month=3,
        waiting_period_hours=48,
        active=True,
        starts_at=now - timedelta(days=10),
    )
    base.update(overrides)
    return Policy(**base)


def make_member(**overrides) -> Member:
    base = dict(
        id="mem_1",
        name="Meena Kumari",
        email="meena@example.com",
        paypal_email="meena.paypal@example.com",
        zone="hyderabad-central",
        verified=True,
        status="active",
        created_at=utcnow() - timedelta(days=30),
    )
    base.update(overrides)
    return Member(**base)


def make_event(**overrides) -> Event:
    base = dict(
        id="evt_1",
        pool_id="pool_1",
        event_key="sim:1",
        trigger_type="rainfall",
        data_source="open-meteo",
        zone="hyderabad-central",
        metric="precipitation_sum_mm_24h",
        value=62.0,
        threshold=50.0,
        days=1,
        mode="simulated",
        status="received",
    )
    base.update(overrides)
    return Event(**base)


def make_pool(**overrides) -> Pool:
    base = dict(
        id="pool_1",
        name="Test pool",
        payout_balance_minor=10_000_000,
        reserve_balance_minor=5_000_000,
        paused=False,
    )
    base.update(overrides)
    return Pool(**base)


def run(**overrides):
    kwargs = dict(
        policy=make_policy(),
        member=make_member(),
        event=make_event(),
        pool=make_pool(),
        risk_score=0,
        days_used_this_month=0,
        payouts_today=0,
        duplicate_decision=False,
    )
    kwargs.update(overrides)
    return evaluate(**kwargs)


def test_happy_path_approves_one_day():
    result = run()
    assert result.outcome == OUTCOME_APPROVE
    assert result.reason_code == REASON_OK
    assert result.payable_days == 1
    assert result.amount_minor == 50_000


def test_two_day_event_pays_two_days():
    result = run(event=make_event(days=2))
    assert result.outcome == OUTCOME_APPROVE
    assert result.payable_days == 2
    assert result.amount_minor == 100_000


def test_threshold_not_met_denies():
    result = run(event=make_event(value=49.9))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_THRESHOLD_NOT_MET
    assert result.amount_minor == 0


def test_threshold_boundary_is_inclusive():
    assert run(event=make_event(value=50.0)).outcome == OUTCOME_APPROVE


def test_zone_mismatch_denies():
    result = run(event=make_event(zone="warangal"))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_ZONE_MISMATCH


def test_waiting_period_blocks_new_members():
    fresh = make_policy(starts_at=utcnow() - timedelta(hours=2))
    result = run(policy=fresh)
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_WAITING_PERIOD


def test_waiting_period_passes_after_48h():
    old = make_policy(starts_at=utcnow() - timedelta(hours=49))
    assert run(policy=old).outcome == OUTCOME_APPROVE


def test_monthly_cap_blocks_after_three_days():
    result = run(days_used_this_month=3)
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_MONTHLY_CAP


def test_monthly_cap_partially_pays_last_available_day():
    result = run(event=make_event(days=2), days_used_this_month=2)
    assert result.outcome == OUTCOME_APPROVE
    assert result.reason_code == REASON_PARTIAL_MONTHLY_CAP
    assert result.payable_days == 1
    assert result.amount_minor == 50_000


def test_daily_cap_blocks_second_payout_same_day():
    result = run(payouts_today=1)
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_DAILY_CAP


def test_paused_pool_blocks_everything():
    result = run(pool=make_pool(paused=True, pause_reason="suspected fraud ring"))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_POOL_PAUSED
    assert "fraud ring" in result.reason_detail


def test_inactive_policy_denies():
    result = run(policy=make_policy(active=False))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_POLICY_INACTIVE


def test_closed_policy_window_denies():
    result = run(policy=make_policy(ends_at=utcnow() - timedelta(days=1)))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_POLICY_WINDOW


def test_blocked_member_denies():
    result = run(member=make_member(status="blocked"))
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_MEMBER_BLOCKED


def test_unverified_member_is_held_not_paid():
    result = run(member=make_member(verified=False))
    assert result.outcome == OUTCOME_HOLD
    assert result.reason_code == REASON_MEMBER_UNVERIFIED


def test_low_pool_holds_instead_of_partial_payment():
    result = run(pool=make_pool(payout_balance_minor=10_000, reserve_balance_minor=5_000))
    assert result.outcome == OUTCOME_HOLD
    assert result.reason_code == REASON_POOL_INSUFFICIENT


def test_reserve_can_cover_a_shortfall():
    pool = make_pool(payout_balance_minor=10_000, reserve_balance_minor=5_000_000)
    result = run(pool=pool)
    assert result.outcome == OUTCOME_APPROVE
    assert pool.total_balance_minor == 5_010_000


def test_high_risk_score_holds_for_human_review():
    result = run(risk_score=70)
    assert result.outcome == OUTCOME_HOLD
    assert result.reason_code == REASON_HIGH_RISK
    assert result.amount_minor == 50_000  # amount is shown but not sent


def test_duplicate_decision_is_denied():
    result = run(duplicate_decision=True)
    assert result.outcome == OUTCOME_DENY
    assert result.reason_code == REASON_DUPLICATE_EVENT


@pytest.mark.parametrize("risk", [0, 20, 39, 69])
def test_below_hold_threshold_still_approves(risk):
    assert run(risk_score=risk).outcome == OUTCOME_APPROVE


def test_reason_detail_is_human_readable():
    result = run()
    assert "62" in result.reason_detail
    assert "50" in result.reason_detail
