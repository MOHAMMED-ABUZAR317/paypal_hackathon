"""Plain-language receipts.

Every member sees *why* they were paid (or not) in one short paragraph, with no
insurance jargon. Baseline templates here are deterministic; the AI layer can
polish wording but never the numbers, which are read straight from the ledger.
"""

from __future__ import annotations

from ..constants import (
    OUTCOME_APPROVE,
    OUTCOME_DENY,
    OUTCOME_HOLD,
    format_inr,
    zone_name,
)


def policy_receipt(
    *,
    name: str,
    zone: str,
    threshold: float,
    payout_minor: int,
    monthly_cap: int,
    waiting_hours: int,
) -> str:
    return (
        f"Hi {name.split()[0]}. You are covered in {zone_name(zone)}. "
        f"If 24-hour rainfall reaches {threshold:g} mm, you get "
        f"{format_inr(payout_minor)} for that day, automatically. "
        f"You can be paid for up to {monthly_cap} rainy days a month, one per day. "
        f"Cover starts {waiting_hours} hours after you join. "
        "You never fill a form, and the weather measurement is the only proof needed."
    )


def payout_receipt(
    *,
    name: str,
    outcome: str,
    reason_code: str,
    reason_detail: str,
    amount_minor: int,
    payable_days: int,
    zone: str,
    rainfall_mm: float | None,
    threshold: float | None,
    status: str | None = None,
    provider: str = "mock",
    send_amount: str | None = None,
    send_currency: str | None = None,
) -> str:
    first = name.split()[0]
    money = (
        " MOCK mode: this is a simulated payout, not real money."
        if provider == "mock"
        else " The money was sent through PayPal."
    )

    if outcome == OUTCOME_APPROVE:
        rain = f"{rainfall_mm:g} mm of rain was measured in {zone_name(zone)}" if rainfall_mm is not None else f"The threshold was crossed in {zone_name(zone)}"
        threshold_text = (
            f", above your agreed {threshold:g} mm" if threshold is not None else ""
        )
        converted = (
            f" (sent as {send_currency} {send_amount})"
            if send_currency and send_amount and send_currency != "INR"
            else ""
        )
        return (
            f"{first}, {rain}{threshold_text}. Your rule triggered, so "
            f"{format_inr(amount_minor)} was approved for {payable_days} day(s)"
            f"{converted}. No claim form, no proof, no waiting. "
            f"Reference: {reason_code}.{money}"
        )

    if outcome == OUTCOME_HOLD:
        return (
            f"{first}, your payout for {zone_name(zone)} is on hold, not denied. "
            f"Reason: {reason_detail} A human will review it before any money moves. "
            f"Reference: {reason_code}."
        )

    return (
        f"{first}, no payout was made for {zone_name(zone)} this time. "
        f"Reason: {reason_detail} Your cover stays active, and you can see the same "
        f"rule that was applied. Reference: {reason_code}."
    )
