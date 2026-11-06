# API reference

Base URL locally: `http://127.0.0.1:8000`. Interactive docs: `/docs`.

Operator routes require the header `X-Operator-Key: <OPERATOR_API_KEY>`
(default `dev-operator-key` locally).

## Meta

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | status, seed state, PayPal/AI mode |
| GET | `/api/config` | public config, zones, hard limits |
| GET | `/api/zones` | zone catalog with coordinates |
| GET | `/api/overview` | pool stats + recent events in one call |

## Policies and members

### `POST /api/policies/parse`

Turn one sentence into a bounded policy preview. Never writes to the database.

```json
POST /api/policies/parse
{ "text": "If rain crosses 50 mm in 24 hours, pay me 500 rupees, up to 3 days a month",
  "zone": "hyderabad-central" }
```

```json
{
  "ok": true,
  "policy": { "threshold": 50.0, "payout_amount_minor": 50000,
              "max_payouts_per_month": 3, "waiting_period_hours": 48,
              "source": "rules", "warnings": [],
              "plain_language": "If 24-hour rainfall in Hyderabad Central reaches 50 mm ..." },
  "attempts": 1
}
```

Rate limit: 30/minute per IP. A rejected trigger returns `ok: false` with a
helpful `error`, not a stack trace.

### `POST /api/policies`

Enroll: create the member and policy after the user confirms the preview.

```json
{
  "member": { "name": "Meena Kumari", "email": "meena@example.com",
              "paypal_email": "meena.paypal@example.com", "zone": "hyderabad-central",
              "device_id": "DEV-123", "signup_ip": "49.207.11.24", "verified": true },
  "policy": { ...PolicyPreview from /parse... },
  "source_text": "If rain crosses 50 mm ..."
}
```

`201` with `member`, `policy`, `screening`, `receipt`, `blocked`. A duplicate
payout address returns `blocked: true` and an inactive policy - the account
cannot receive money.

`409` if the email already exists.

### Other reads

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/policies?member_id=` | policies for a member |
| PATCH | `/api/policies/{id}?active=` | operator toggle |
| GET | `/api/members?q=&limit=` | search members |
| GET | `/api/members/{id}` | member + policies + receipts |

## Pool funding

### `POST /api/pool/fund`

```json
{ "member_id": "mem_...", "amount_minor": 10000 }
```

Creates a PayPal order (or a labelled mock order). Returns
`contribution_id`, `order_id`, `approve_url`, `provider`, `mock`.

### `POST /api/pool/fund/{order_id}/capture`

Captures the order and credits the pool 70% payout box / 20% reserve /
10% running costs. Idempotent: a second capture of the same order returns the
same completed contribution and does not double-credit.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/pool` | balances |
| GET | `/api/pool/stats` | dashboard aggregates, coverage, forecast, guards |
| GET | `/api/contributions` | funding history |

## Events

### `POST /api/events/simulate` (operator)

```json
{ "zone": "hyderabad-central", "rainfall_mm": 62, "days": 1,
  "event_key": "optional-replay-key" }
```

Runs the full pipeline. Response includes `counts`, `reasons`,
`total_paid_minor`, `payout_rows`, `batches`, `duration_ms`, `decisions_sample`.

Reuse the same `event_key` to prove idempotency: the response returns
`duplicate: true` and adds no second payout.

### `POST /api/events/poll` (operator)

Polls Open-Meteo for all six zones now. Fail-closed: a feed error produces
`status: "feed_error"` and no event.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/events?limit=` | recent events |
| GET | `/api/events/{id}` | full summary for one event |
| GET | `/api/events/{id}/last-key` | reuse key for a replay demo |

## Ledger and receipts

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ledger?status=&zone=&event_id=&q=&limit=&offset=` | payout ledger with reason codes |
| GET | `/api/decisions?event_id=&outcome=` | every decision, including denies and holds |
| GET | `/api/receipts?member_id=&limit=` | plain-language receipts |
| GET | `/api/receipts/{payout_id}` | one receipt |
| GET | `/api/audit?action=&limit=` | append-only audit trail |

## Operator

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/operator/pause` | `{ "paused": true, "reason": "..." }` |
| POST | `/api/operator/payouts/retry` | retry failed payouts (`event_id` optional) |
| POST | `/api/operator/payouts/reconcile` | ask PayPal for PENDING batch status |
| POST | `/api/operator/demo/reset` | clear events/payouts, restore balances, keep members |
| POST | `/api/operator/demo/fraud-attempt` | blocked sybil enrollment demo |

## Webhooks

`POST /api/webhooks/paypal` - verifies `PAYPAL-TRANSMISSION-*` signatures against
`PAYPAL_WEBHOOK_ID` before any state change. Handles payout item success/failure,
batch status and capture completion. Invalid signature = HTTP 400, no mutation.
Replays are idempotent.

## Error format

```json
{ "detail": "Human-readable reason", "hint": "optional next step" }
```

| Code | Meaning |
|---|---|
| 400 | validation / unknown zone / bad signature |
| 401 | missing or wrong operator key |
| 404 | resource not found |
| 409 | duplicate email, incomplete capture |
| 429 | rate limited |
| 502 | PayPal rejected the call |
| 503 | demo seed missing |
