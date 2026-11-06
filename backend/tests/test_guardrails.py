"""Idempotency and fraud tests - the guardrails the demo puts on screen."""

from __future__ import annotations

from tests.conftest import OPERATOR_HEADERS


def simulate(client, **overrides):
    payload = {"zone": "hyderabad-central", "rainfall_mm": 62, "days": 1}
    payload.update(overrides)
    return client.post("/api/events/simulate", json=payload, headers=OPERATOR_HEADERS)


def test_replaying_the_same_event_pays_nothing_twice(seeded_client):
    first = simulate(seeded_client, event_key="demo-replay-001").json()
    second = simulate(seeded_client, event_key="demo-replay-001").json()

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["event"]["id"] == first["event"]["id"]
    assert second["payout_rows"] == first["payout_rows"]
    assert second["total_paid_minor"] == first["total_paid_minor"]

    ledger = seeded_client.get("/api/ledger?limit=1000").json()
    for row in ledger["rows"]:
        if row["event_id"] == first["event"]["id"]:
            assert row["status"] == "SUCCESS"


def test_unique_decision_per_event_and_policy(seeded_client):
    summary = simulate(seeded_client, event_key="demo-unique-001").json()
    event_id = summary["event"]["id"]
    decisions = seeded_client.get(f"/api/decisions?event_id={event_id}&limit=1000").json()
    pairs = [(d["event_id"], d["member_id"]) for d in decisions["decisions"]]
    assert len(pairs) == len(set(pairs))


def test_second_event_same_day_hits_the_daily_cap(seeded_client):
    first = simulate(seeded_client, event_key="cap-1", days=1).json()
    assert first["counts"]["APPROVE"] > 0

    # A second storm event on the same calendar day cannot pay the same member
    # twice: that is the per-person, per-day cap doing its job.
    second = simulate(seeded_client, event_key="cap-2", days=1).json()
    assert second["counts"]["APPROVE"] == 0
    codes = {reason["code"] for reason in second["reasons"]}
    assert "DAILY_CAP_REACHED" in codes


def test_duplicate_payout_destination_blocks_enrollment(seeded_client):
    parsed = seeded_client.post(
        "/api/policies/parse",
        json={
            "text": "If rain crosses 50 mm in 24 hours, pay me 500 rupees.",
            "zone": "hyderabad-central",
        },
    ).json()

    response = seeded_client.post(
        "/api/policies",
        json={
            "member": {
                "name": "Sybil Account",
                "email": "sybil.new@example.com",
                "paypal_email": "ring-collector@example.com",
                "zone": "hyderabad-central",
                "device_id": "DEV-NEW-1",
                "signup_ip": "198.51.100.77",
                "verified": True,
            },
            "policy": parsed["policy"],
            "source_text": "fraud attempt",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["blocked"] is True
    assert body["member"]["status"] == "blocked"
    assert body["policy"]["active"] is False
    assert body["screening"]["score"] >= 70
    assert any(
        flag["code"] == "DUPLICATE_PAYOUT_DESTINATION"
        for flag in body["screening"]["flags"]
    )


def test_ring_members_are_held_at_payout_time(seeded_client):
    summary = simulate(seeded_client, event_key="ring-demo-1").json()
    assert summary["counts"]["HOLD_FOR_REVIEW"] > 0
    codes = {reason["code"] for reason in summary["reasons"]}
    assert "HIGH_RISK_HOLD" in codes

    held = seeded_client.get("/api/decisions?outcome=HOLD_FOR_REVIEW").json()["decisions"]
    assert held
    assert all(row["risk_score"] >= 70 for row in held)


def test_unverified_members_are_held(seeded_client):
    summary = simulate(seeded_client, event_key="unverified-demo-1", zone="hyderabad-north").json()
    codes = {reason["code"] for reason in summary["reasons"]}
    assert "MEMBER_NOT_VERIFIED" in codes


def test_new_members_are_inside_waiting_period(seeded_client):
    summary = simulate(seeded_client, event_key="waiting-demo-1").json()
    codes = {reason["code"] for reason in summary["reasons"]}
    assert "WAITING_PERIOD_NOT_MET" in codes


def test_fraud_attempt_demo_endpoint(seeded_client):
    response = seeded_client.post(
        "/api/operator/demo/fraud-attempt", headers=OPERATOR_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert "DUPLICATE_PAYOUT_DESTINATION" in [f["code"] for f in body["screening"]["flags"]]
    assert "refused" in body["receipt"].lower()


def test_payout_retry_only_touches_failed_rows(seeded_client):
    response = seeded_client.post(
        "/api/operator/payouts/retry", json={}, headers=OPERATOR_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["retried"] == 0


def test_webhook_rejects_unverified_payload_when_not_mock(client):
    # In mock mode the transport is explicitly labelled and accepts; ensure the
    # response is honest about that rather than silently claiming PayPal verified it.
    response = client.post(
        "/api/webhooks/paypal",
        json={"event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "resource": {}},
    )
    assert response.status_code == 200
    assert response.json()["verification"] == "mock"


def test_webhook_updates_payout_status(seeded_client):
    summary = simulate(seeded_client, event_key="webhook-demo-1").json()
    ledger = seeded_client.get(
        f"/api/ledger?event_id={summary['event']['id']}&limit=1000"
    ).json()
    row = next(r for r in ledger["rows"] if r["item_id"])
    assert row["status"] == "SUCCESS"

    response = seeded_client.post(
        "/api/webhooks/paypal",
        json={
            "event_type": "PAYMENT.PAYOUTS-ITEM.FAILED",
            "resource": {
                "payout_item_id": row["item_id"],
                "payout_batch_id": row["batch_id"],
                "transaction_status": "FAILED",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["rows_changed"] == 1

    after = seeded_client.get(f"/api/receipts/{row['id']}").json()["receipt"]
    assert after["status"] == "FAILED"
