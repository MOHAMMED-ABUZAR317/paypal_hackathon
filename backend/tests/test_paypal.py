"""Unit tests for the PayPal integration layer (member 1).

Runs fully offline against the deterministic mock transport.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.services.paypal import (
    MAX_ITEMS_PER_BATCH,
    PayPalClient,
    PayPalError,
    stable_id,
    to_payout_amount,
)


def run(coro):
    return asyncio.run(coro)


def mock_settings(**overrides) -> Settings:
    base = dict(
        paypal_mode="mock",
        paypal_client_id="",
        paypal_client_secret="",
        paypal_payout_currency="USD",
        payout_inr_per_usd=83.0,
    )
    base.update(overrides)
    return Settings(**base)


# ----------------------------------------------------------------- currency
@pytest.mark.parametrize(
    "paise,expected",
    [
        (50_000, "6.02"),   # Rs 500 at 83/USD
        (10_000, "1.20"),   # Rs 100 monthly contribution
        (100, "0.01"),      # Re 1 -> floors at one cent
        (0, "0.01"),        # never send zero
    ],
)
def test_inr_to_usd_conversion(paise, expected):
    assert to_payout_amount(paise, "USD", 83.0) == expected


def test_inr_payout_currency_passthrough():
    assert to_payout_amount(50_000, "INR", 83.0) == "500.00"


# ---------------------------------------------------------------- idempotency
def test_stable_id_is_deterministic_and_paypal_safe():
    a = stable_id("MOCKBATCH", "evt-1", "run-1")
    b = stable_id("MOCKBATCH", "evt-1", "run-1")
    c = stable_id("MOCKBATCH", "evt-1", "run-2")
    assert a == b
    assert a != c
    assert len(a) <= 32 and a.isalnum()


# --------------------------------------------------------------------- Orders
def test_create_order_mock_is_idempotent():
    client = PayPalClient(mock_settings())

    async def scenario():
        first = await client.create_order(
            amount_minor=10_000,
            currency="INR",
            description="RainCheck pool contribution",
            reference_id="pool-1",
            idempotency_key="fund:member-1:2026-11",
        )
        second = await client.create_order(
            amount_minor=10_000,
            currency="INR",
            description="RainCheck pool contribution",
            reference_id="pool-1",
            idempotency_key="fund:member-1:2026-11",
        )
        return first, second

    first, second = run(scenario())
    assert first["id"] == second["id"]
    assert first["provider"] == "mock"
    assert first["purchase_units"][0]["amount"]["value"] == "100.00"
    assert any(link["rel"] == "approve" for link in first["links"])


def test_capture_order_mock_completes():
    client = PayPalClient(mock_settings())
    result = run(client.capture_order("MOCKORDER123"))
    assert result["status"] == "COMPLETED"
    assert result["mock"] is True
    assert result["purchase_units"][0]["payments"]["captures"][0]["status"] == "COMPLETED"


# -------------------------------------------------------------------- Payouts
def test_payout_batch_rejects_empty_items():
    client = PayPalClient(mock_settings())
    with pytest.raises(PayPalError):
        run(client.create_payout_batch(sender_batch_id="b1", items=[]))


def test_payout_batch_mock_pays_every_item_once():
    client = PayPalClient(mock_settings())
    items = [
        {
            "sender_item_id": f"evt1:policy-{i}",
            "receiver": f"worker{i}@example.com",
            "amount": "6.02",
            "currency": "USD",
            "note": "RainCheck payout: 62mm rain",
        }
        for i in range(3)
    ]
    result = run(client.create_payout_batch(sender_batch_id="batch-evt1", items=items))
    header = result["batch_header"]
    assert header["batch_status"] == "SUCCESS"
    assert header["items"] == 3
    assert len(result["items"]) == 3
    # Distinct sender_item_ids must produce distinct PayPal item ids.
    ids = {item["payout_item_id"] for item in result["items"]}
    assert len(ids) == 3
    assert all(item["transaction_status"] == "SUCCESS" for item in result["items"])


def test_payout_batch_ids_are_stable_across_retries():
    client = PayPalClient(mock_settings())
    items = [
        {
            "sender_item_id": "evt9:policy-42",
            "receiver": "worker@example.com",
            "amount": "6.02",
            "currency": "USD",
        }
    ]
    first = run(client.create_payout_batch(sender_batch_id="batch-evt9", items=items))
    second = run(client.create_payout_batch(sender_batch_id="batch-evt9", items=items))
    assert first["batch_header"]["payout_batch_id"] == second["batch_header"]["payout_batch_id"]
    assert first["items"][0]["payout_item_id"] == second["items"][0]["payout_item_id"]


def test_batch_chunk_limit_is_sane():
    assert 1 < MAX_ITEMS_PER_BATCH <= 15_000


# -------------------------------------------------------------------- Webhooks
def test_mock_webhook_is_accepted_and_labelled():
    client = PayPalClient(mock_settings())
    result = run(client.verify_webhook({}, b'{"event_type":"PAYMENT.PAYOUTS-ITEM.SUCCEEDED"}'))
    assert result.verified is True
    assert result.mode == "mock"
    assert "mock" in result.reason.lower()


def test_real_mode_without_webhook_id_rejects():
    client = PayPalClient(
        mock_settings(
            paypal_mode="sandbox",
            paypal_client_id="id",
            paypal_client_secret="secret",
            paypal_webhook_id="",
        )
    )
    result = run(client.verify_webhook({}, b"{}"))
    assert result.verified is False
    assert "PAYPAL_WEBHOOK_ID" in result.reason


def test_real_mode_without_signature_headers_rejects():
    client = PayPalClient(
        mock_settings(
            paypal_mode="sandbox",
            paypal_client_id="id",
            paypal_client_secret="secret",
            paypal_webhook_id="WH-TEST",
        )
    )
    result = run(client.verify_webhook({"paypal-auth-algo": "SHA256withRSA"}, b"{}"))
    assert result.verified is False
    assert "Missing signature headers" in result.reason
