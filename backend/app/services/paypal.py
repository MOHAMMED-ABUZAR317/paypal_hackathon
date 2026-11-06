"""PayPal integration: Orders (funding), Payouts (disbursement), webhooks.

Design rules enforced here:

* This module is the **only** place in the codebase that talks to PayPal.
* Every outbound money movement carries an idempotency key supplied by the
  caller. PayPal's own ``sender_batch_id`` / ``sender_item_id`` fields are
  derived from those keys, so a retry can never create a second payment.
* When ``PAYPAL_MODE=mock`` (or credentials are missing) the client returns
  realistic, deterministic sandbox-shaped responses with ``provider="mock"``.
  Every caller, API response and screen surfaces that label. The demo never
  pretends mock money is real money.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger("raincheck.paypal")

# PayPal Payouts accepts at most 15,000 items per batch. We chunk well below
# that so a single oversized request can never fail the whole event.
MAX_ITEMS_PER_BATCH = 500


class PayPalError(RuntimeError):
    """Raised when PayPal (or the mock transport) cannot fulfil a request."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_id(prefix: str, *parts: str, length: int = 20) -> str:
    """Deterministic, PayPal-safe identifier derived from idempotency inputs."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:length]}"


def to_payout_amount(amount_inr_minor: int, currency: str, inr_per_usd: float) -> str:
    """Convert an INR minor-unit amount into the payout currency (2dp string).

    PayPal Payouts does not support INR, so the sandbox payout is denominated in
    USD at a clearly documented, configurable rate. The worker-facing ledger
    always shows the INR amount they are protected for.
    """
    inr_major = Decimal(amount_inr_minor) / Decimal(100)
    if currency.upper() == "INR":
        value = inr_major
    else:
        rate = Decimal(str(inr_per_usd or 83.0))
        value = inr_major / rate
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized < Decimal("0.01"):
        quantized = Decimal("0.01")
    return f"{quantized:.2f}"


@dataclass
class WebhookVerification:
    verified: bool
    mode: str  # "paypal" | "mock"
    reason: str = ""


class PayPalClient:
    """Thin async wrapper over the PayPal REST APIs used by RainCheck."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------ mode
    @property
    def is_mock(self) -> bool:
        return not self.settings.use_real_paypal

    @property
    def provider(self) -> str:
        return "mock" if self.is_mock else "paypal"

    # ------------------------------------------------------------------ auth
    async def _access_token(self) -> str:
        if self.is_mock:
            return "mock-access-token"
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        url = f"{self.settings.paypal_api_base}/v1/oauth2/token"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                data={"grant_type": "client_credentials"},
                auth=(
                    self.settings.paypal_client_id,
                    self.settings.paypal_client_secret,
                ),
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200:
            raise PayPalError(
                f"PayPal OAuth failed ({response.status_code}): {response.text[:300]}"
            )
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 32000))
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        extra_headers: dict | None = None,
    ) -> dict:
        token = await self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }
        headers.update(extra_headers or {})
        url = f"{self.settings.paypal_api_base}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, url, headers=headers, json=json_body
            )
        if response.status_code >= 400:
            raise PayPalError(
                f"PayPal {method} {path} failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
        if not response.content:
            return {}
        return response.json()

    # ---------------------------------------------------------------- Orders
    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        description: str,
        reference_id: str,
        idempotency_key: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict:
        """Create a PayPal order so a member can fund the pool."""
        amount = f"{Decimal(amount_minor) / Decimal(100):.2f}"
        if self.is_mock:
            order_id = stable_id("MOCKORDER", idempotency_key)
            return {
                "id": order_id,
                "status": "CREATED",
                "provider": "mock",
                "mock": True,
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": reference_id,
                        "description": description,
                        "amount": {"currency_code": currency, "value": amount},
                    }
                ],
                "links": [
                    {
                        "rel": "approve",
                        "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                        "method": "GET",
                    }
                ],
                "create_time": _utc_now_iso(),
            }

        body: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "description": description[:127],
                    "custom_id": idempotency_key[:127],
                    "amount": {"currency_code": currency, "value": amount},
                }
            ],
            "application_context": {
                "brand_name": "RainCheck",
                "user_action": "PAY_NOW",
                "shipping_preference": "NO_SHIPPING",
            },
        }
        if return_url:
            body["application_context"]["return_url"] = return_url
        if cancel_url:
            body["application_context"]["cancel_url"] = cancel_url
        payload = await self._request(
            "POST",
            "/v2/checkout/orders",
            json_body=body,
            extra_headers={"PayPal-Request-Id": idempotency_key[:108]},
        )
        payload["provider"] = "paypal"
        payload["mock"] = False
        return payload

    async def capture_order(self, order_id: str) -> dict:
        """Capture an approved order. Safe to retry: PayPal keys on order id."""
        if self.is_mock:
            capture_id = stable_id("MOCKCAPTURE", order_id)
            return {
                "id": order_id,
                "status": "COMPLETED",
                "provider": "mock",
                "mock": True,
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": capture_id,
                                    "status": "COMPLETED",
                                    "create_time": _utc_now_iso(),
                                }
                            ]
                        }
                    }
                ],
            }
        payload = await self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            json_body={},
            extra_headers={"PayPal-Request-Id": f"capture-{order_id}"[:108]},
        )
        payload["provider"] = "paypal"
        payload["mock"] = False
        return payload

    # --------------------------------------------------------------- Payouts
    async def create_payout_batch(
        self,
        *,
        sender_batch_id: str,
        items: Iterable[dict],
        email_subject: str = "Your RainCheck payout has arrived",
        email_message: str = "An objective weather trigger fired in your zone.",
    ) -> dict:
        """Create one Payouts batch.

        ``items`` entries must be::

            {
              "sender_item_id": "<idempotency key>",   # unique per item
              "receiver": "worker@example.com",
              "amount": "6.02",
              "currency": "USD",
              "note": "RainCheck payout for 50mm+ rainfall",
            }
        """
        item_list = list(items)
        if not item_list:
            raise PayPalError("Cannot create a payout batch with zero items")

        if self.is_mock:
            batch_id = stable_id("MOCKBATCH", sender_batch_id)
            mock_items = []
            for item in item_list:
                item_id = stable_id("MOCKITEM", sender_batch_id, item["sender_item_id"])
                mock_items.append(
                    {
                        "payout_item_id": item_id,
                        "transaction_id": stable_id("MOCKTXN", item_id),
                        "transaction_status": "SUCCESS",
                        "payout_item_fee": {"currency": item["currency"], "value": "0.25"},
                        "payout_item": {
                            "recipient_type": "EMAIL",
                            "amount": {
                                "value": item["amount"],
                                "currency": item["currency"],
                            },
                            "receiver": item["receiver"],
                            "note": item.get("note", "")[:255],
                            "sender_item_id": item["sender_item_id"],
                        },
                        "time_processed": _utc_now_iso(),
                    }
                )
            return {
                "batch_header": {
                    "payout_batch_id": batch_id,
                    "batch_status": "SUCCESS",
                    "sender_batch_header": {
                        "sender_batch_id": sender_batch_id,
                        "email_subject": email_subject,
                        "email_message": email_message,
                    },
                    "time_created": _utc_now_iso(),
                    "amount": {
                        "currency": item_list[0]["currency"],
                        "value": f"{sum(Decimal(i['amount']) for i in item_list):.2f}",
                    },
                    "fees": {
                        "currency": item_list[0]["currency"],
                        "value": f"{Decimal('0.25') * len(item_list):.2f}",
                    },
                    "items": len(item_list),
                },
                "items": mock_items,
                "provider": "mock",
                "mock": True,
            }

        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id[:256],
                "email_subject": email_subject[:255],
                "email_message": email_message[:1000],
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": item["amount"],
                        "currency": item["currency"],
                    },
                    "receiver": item["receiver"],
                    "note": item.get("note", "")[:255],
                    "sender_item_id": item["sender_item_id"][:63],
                    "notification_language": "en-US",
                }
                for item in item_list
            ],
        }
        payload = await self._request(
            "POST",
            "/v1/payments/payouts",
            json_body=body,
            extra_headers={"PayPal-Request-Id": sender_batch_id[:108]},
        )
        payload["provider"] = "paypal"
        payload["mock"] = False
        return payload

    async def get_payout_batch(self, batch_id: str) -> dict:
        if self.is_mock:
            return {
                "batch_header": {
                    "payout_batch_id": batch_id,
                    "batch_status": "SUCCESS",
                },
                "provider": "mock",
                "mock": True,
            }
        payload = await self._request("GET", f"/v1/payments/payouts/{batch_id}")
        payload["provider"] = "paypal"
        payload["mock"] = False
        return payload

    # -------------------------------------------------------------- Webhooks
    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookVerification:
        """Verify a webhook came from PayPal before mutating any state."""
        if self.is_mock:
            return WebhookVerification(
                verified=True,
                mode="mock",
                reason="PAYPAL_MODE=mock: signature check bypassed for local demo",
            )
        webhook_id = self.settings.paypal_webhook_id
        if not webhook_id:
            return WebhookVerification(False, "paypal", "PAYPAL_WEBHOOK_ID is not set")

        try:
            event = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return WebhookVerification(False, "paypal", "Body is not valid JSON")

        verification_body = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        missing = [k for k, v in verification_body.items() if not v and k != "webhook_id"]
        if missing:
            return WebhookVerification(
                False, "paypal", f"Missing signature headers: {', '.join(sorted(missing))}"
            )
        try:
            payload = await self._request(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                json_body=verification_body,
            )
        except PayPalError as exc:
            return WebhookVerification(False, "paypal", str(exc))
        if payload.get("verification_status") == "SUCCESS":
            return WebhookVerification(True, "paypal", "Signature verified")
        return WebhookVerification(
            False, "paypal", f"verification_status={payload.get('verification_status')}"
        )


_client: PayPalClient | None = None


def get_paypal_client() -> PayPalClient:
    global _client
    if _client is None:
        _client = PayPalClient()
    return _client


def reset_paypal_client() -> None:
    """Test helper: drop the cached client after env/settings changes."""
    global _client
    _client = None
