"""End-to-end API tests: parse -> enroll -> fund -> trigger -> pay -> ledger."""

from __future__ import annotations

from tests.conftest import OPERATOR_HEADERS

SENTENCE = (
    "If heavy rain crosses 50 mm in 24 hours in Hyderabad Central, "
    "pay me 500 rupees, up to 3 days a month."
)


def enroll(client, email="test.member@example.com", paypal="test.paypal@example.com",
           zone="hyderabad-central", verified=True, device="DEV-TEST-1"):
    parsed = client.post("/api/policies/parse", json={"text": SENTENCE, "zone": zone})
    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert body["ok"] is True
    payload = {
        "member": {
            "name": "Test Member",
            "email": email,
            "paypal_email": paypal,
            "zone": zone,
            "device_id": device,
            "signup_ip": "198.51.100.9",
            "verified": verified,
        },
        "policy": body["policy"],
        "source_text": SENTENCE,
    }
    return client.post("/api/policies", json=payload)


def test_health_and_config(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json()["app"]["paypal"]["mode"] == "mock"
    assert len(config.json()["zones"]) == 6


def test_parse_returns_bounded_policy(client):
    response = client.post(
        "/api/policies/parse", json={"text": SENTENCE, "zone": "hyderabad-central"}
    )
    policy = response.json()["policy"]
    assert policy["threshold"] == 50.0
    assert policy["payout_amount_minor"] == 50_000
    assert policy["max_payouts_per_month"] == 3
    assert policy["source"] == "rules"
    assert "rainfall" in policy["plain_language"].lower()


def test_parse_rejects_non_rain_trigger(client):
    response = client.post(
        "/api/policies/parse",
        json={"text": "Pay me 500 if there is an earthquake", "zone": "hyderabad-central"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "rainfall" in response.json()["error"].lower()


def test_enrollment_creates_member_and_policy(seeded_client):
    response = enroll(seeded_client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["blocked"] is False
    assert body["member"]["status"] == "active"
    assert body["policy"]["active"] is True
    assert "Meena" not in body["receipt"]  # receipt addresses the new member
    assert "50 mm" in body["receipt"]


def test_duplicate_email_is_rejected(seeded_client):
    assert enroll(seeded_client, email="dupe@example.com").status_code == 201
    second = enroll(seeded_client, email="dupe@example.com", paypal="other@example.com")
    assert second.status_code == 409


def test_full_storm_flow_pays_and_updates_ledger(seeded_client):
    before = seeded_client.get("/api/pool/stats").json()

    response = seeded_client.post(
        "/api/events/simulate",
        json={"zone": "hyderabad-central", "rainfall_mm": 62, "days": 1},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["duplicate"] is False
    assert summary["counts"]["APPROVE"] > 0
    assert summary["total_paid_minor"] > 0
    assert summary["payout_result"]["mock"] is True

    ledger = seeded_client.get("/api/ledger").json()
    assert ledger["total"] > 0
    assert all(row["status"] in {"SUCCESS", "PENDING", "FAILED"} for row in ledger["rows"])
    assert any(row["provider"] == "mock" for row in ledger["rows"])

    after = seeded_client.get("/api/pool/stats").json()
    assert (
        after["pool"]["payout_balance_minor"]
        < before["pool"]["payout_balance_minor"]
    )
    assert after["performance"]["payouts_success"] > 0
    assert after["performance"]["avg_seconds_trigger_to_payout"] is not None


def test_simulate_requires_operator_key(seeded_client):
    response = seeded_client.post(
        "/api/events/simulate",
        json={"zone": "hyderabad-central", "rainfall_mm": 62},
    )
    assert response.status_code == 401


def test_below_threshold_denies_everyone(seeded_client):
    response = seeded_client.post(
        "/api/events/simulate",
        json={"zone": "hyderabad-central", "rainfall_mm": 12, "days": 1},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["APPROVE"] == 0
    assert body["total_paid_minor"] == 0
    assert any(reason["code"] == "THRESHOLD_NOT_MET" for reason in body["reasons"])


def test_receipts_are_generated_for_payouts(seeded_client):
    seeded_client.post(
        "/api/events/simulate",
        json={"zone": "hyderabad-central", "rainfall_mm": 62, "days": 1},
        headers=OPERATOR_HEADERS,
    )
    receipts = seeded_client.get("/api/receipts?limit=5").json()["receipts"]
    assert receipts
    first = receipts[0]
    assert first["text"]
    assert "MOCK" in first["text"] or "simulated" in first["text"].lower()


def test_pause_switch_blocks_payouts(seeded_client):
    pause = seeded_client.post(
        "/api/operator/pause",
        json={"paused": True, "reason": "demo: checking the emergency stop"},
        headers=OPERATOR_HEADERS,
    )
    assert pause.status_code == 200
    assert pause.json()["pool"]["paused"] is True

    response = seeded_client.post(
        "/api/events/simulate",
        json={"zone": "hyderabad-central", "rainfall_mm": 80},
        headers=OPERATOR_HEADERS,
    )
    body = response.json()
    assert body["counts"]["APPROVE"] == 0
    assert any(reason["code"] == "POOL_PAUSED" for reason in body["reasons"])

    seeded_client.post(
        "/api/operator/pause",
        json={"paused": False},
        headers=OPERATOR_HEADERS,
    )


def test_live_poll_is_fail_closed_or_processes(seeded_client):
    """Open-Meteo may be unreachable in CI; either way no payout may fire on error."""
    response = seeded_client.post("/api/events/poll", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["zones_checked"] == 6
    for result in body["results"]:
        assert result["status"] in {"processed", "duplicate", "below_threshold", "feed_error"}
        if result["status"] == "feed_error":
            assert "event_id" not in result


def test_demo_reset_removes_rehearsal_members(seeded_client):
    """Reset returns the demo to its seed baseline, including free emails."""
    baseline = seeded_client.get("/api/pool/stats").json()
    baseline_members = baseline["members"]["total"]

    assert enroll(seeded_client, email="rehearsal@example.com").status_code == 201
    fraud = seeded_client.post(
        "/api/operator/demo/fraud-attempt", headers=OPERATOR_HEADERS
    )
    assert fraud.status_code == 200
    assert fraud.json()["blocked"] is True
    assert seeded_client.get("/api/pool/stats").json()["members"]["total"] == baseline_members + 2

    reset = seeded_client.post("/api/operator/demo/reset", headers=OPERATOR_HEADERS)
    assert reset.status_code == 200
    assert reset.json()["rehearsal_members_removed"] == 2

    after = seeded_client.get("/api/pool/stats").json()
    assert after["members"]["total"] == baseline_members
    assert after["members"]["policies_active"] == baseline["members"]["policies_active"]
    assert after["pool"]["paused"] is False
    # The email is free again, so the same rehearsal can run twice.
    assert enroll(seeded_client, email="rehearsal@example.com").status_code == 201
