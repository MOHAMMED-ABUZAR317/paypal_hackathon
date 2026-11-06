# PayPal integration

RainCheck uses three PayPal surfaces. Each one is required for a different part
of the flow, and each is visible in the demo.

| Surface | Where it is used | Code |
| --- | --- | --- |
| **Orders v2** | A member funds the shared pool (Rs 100/month) | `POST /api/pool/fund`, `POST /api/pool/fund/{order_id}/capture` |
| **Payouts v1** | Automatic disbursement the moment a trigger fires | `POST /api/events/simulate` -> payout service |
| **Webhooks** | Confirms payout/item status before the ledger is final | `POST /api/webhooks/paypal` |

Everything lives in `backend/app/services/paypal.py`. It is the **only** module
that can reach PayPal; the AI layer has no import path to it.

## 1. Orders (funding)

```
POST /v2/checkout/orders          intent=CAPTURE
  purchase_units[0].amount        { currency_code: "INR", value: "100.00" }
  purchase_units[0].custom_id     idempotency key
  PayPal-Request-Id               same idempotency key
POST /v2/checkout/orders/{id}/capture
```

The frontend redirects to the `approve` link in sandbox mode. The capture is
only trusted after the API response says `COMPLETED`; the browser redirect alone
is never treated as proof of payment.

## 2. Payouts (disbursement)

```
POST /v1/payments/payouts
  sender_batch_header.sender_batch_id   "rc-<event>-<run>"
  items[].sender_item_id                "<event_id>:<policy_id>"
  items[].receiver                      member's verified PayPal email
  items[].amount                        USD (PayPal Payouts has no INR support)
  items[].note                          plain-language reason
```

* `sender_batch_id` and `sender_item_id` are **derived from the domain
  idempotency key**, so a retry of the same event replays the same ids instead
  of paying twice.
* Batches are chunked at `MAX_ITEMS_PER_BATCH = 500` items.
* The INR amount is converted at `PAYOUT_INR_PER_USD` (default 83.00) and the
  ledger stores both the protected INR amount and the sent USD amount. This is
  documented openly; the UI labels the conversion.
* Payout item status is **not** taken from the create response as final. The row
  is written as `PENDING` and only becomes `SUCCESS` / `FAILED` from a verified
  webhook (or an explicit reconciliation call).

## 3. Webhooks

```
POST /v1/notifications/verify-webhook-signature
  auth_algo, cert_url, transmission_id, transmission_sig,
  transmission_time, webhook_id, webhook_event
```

The receiver verifies the signature **before** mutating any state. It then maps:

| PayPal event | RainCheck effect |
| --- | --- |
| `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` | payout -> `SUCCESS`, audit entry, Zapier notification |
| `PAYMENT.PAYOUTS-ITEM.FAILED` / `.BLOCKED` / `.RETURNED` | payout -> `FAILED` + reason, retry path |
| `PAYMENT.CAPTURE.COMPLETED` | contribution -> `COMPLETED`, pool balance updated |

Unverified deliveries return HTTP 400 and are logged with `signature_valid=false`.

## Mock mode

`PAYPAL_MODE=mock` (the default, and the automatic fallback when credentials are
missing) produces deterministic, sandbox-shaped responses with:

* `provider: "mock"`
* `mock: true`
* ids derived from the idempotency key, so tests can assert replays

Every API response, ledger row and screen shows the label. Nothing in the UI
claims mock money is real. This is deliberate: the judging notes ask for an
honest fallback rather than a fake success.

Switch to real sandbox calls with:

```env
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_WEBHOOK_ID=...
PAYPAL_SENDER_EMAIL=your-sandbox-business@example.com
```

## Failure handling

| Failure | Behaviour |
| --- | --- |
| OAuth fails | `PayPalError`, payout stays `PENDING`, operator sees the error, retry is safe |
| Batch rejected | item rows -> `FAILED` with PayPal's message, `/operator/payouts/retry` re-sends only failed items |
| Duplicate event | idempotency key already exists -> no second decision, no second batch |
| Webhook missing/invalid signature | HTTP 400, nothing changes |
| Payouts restricted on the account | mock mode keeps the demo alive and is labelled as such |

## Sandbox checklist (member 1, manual)

1. <https://developer.paypal.com/dashboard/applications/sandbox> -> **Create App**.
2. Copy the **Client ID** and **Secret** into `.env` (`PAYPAL_MODE=sandbox`).
3. Create a **personal** sandbox account to receive money; use its email as the
   member payout destination (or as `PAYPAL_SENDER_EMAIL` for the business side).
4. Under the app -> **Webhooks**, add
   `https://<your-backend>/api/webhooks/paypal` and subscribe to
   `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `PAYMENT.PAYOUTS-ITEM.FAILED`,
   `PAYMENT.CAPTURE.COMPLETED`. Copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID`.
5. Run `python -m scripts.smoke_paypal` (see `docs/RUNBOOK.md`) to prove one
   order and one payout before the demo.
