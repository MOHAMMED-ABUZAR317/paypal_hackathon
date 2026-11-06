# Policy schema v1.0 (frozen)

The policy object is the contract between the AI parser, the API, the rule
engine and the frontend. It was frozen at the end of checkpoint 1 so all three
tracks could work in parallel.

## Shape

```json
{
  "schema_version": "1.0",
  "trigger_type": "rainfall",
  "data_source": "open-meteo",
  "zone": "hyderabad-central",
  "metric": "precipitation_sum_mm_24h",
  "operator": ">=",
  "threshold": 50.0,
  "payout_amount_minor": 50000,
  "currency": "INR",
  "max_payouts_per_day": 1,
  "max_payouts_per_month": 3,
  "waiting_period_hours": 48,
  "plain_language": "If 24-hour rainfall in Hyderabad Central reaches 50 mm ...",
  "source": "rules",
  "warnings": [],
  "confidence": 0.8
}
```

`plain_language`, `source`, `warnings` and `confidence` are explanation-layer
fields. The rule engine ignores them entirely.

## Hard bounds (server-side, not model-side)

| Field | Allowed | Enforced by |
|---|---|---|
| `trigger_type` | `rainfall` only in v1 | `enforce_bounds` raises on anything else |
| `operator` | `>=` | coerced to `>=` |
| `threshold` | 5 - 300 mm / 24h | clamped |
| `payout_amount_minor` | 5,000 - 200,000 paise (Rs 50 - Rs 2,000) | clamped |
| `max_payouts_per_day` | exactly 1 | forced |
| `max_payouts_per_month` | 1 - 3 days | clamped |
| `waiting_period_hours` | 24 - 168 h | clamped |
| `zone` | one of the six seeded zones | validated against the zone catalog |
| `currency` | INR (pool), converted for PayPal Payouts | forced |

Every clamp is appended to `warnings` and shown to the user before they confirm.
A hostile sentence asking for Rs 99,999 produces a bounded Rs 2,000 policy and
an explicit warning - it cannot change the limits.

## Amount units

All amounts are integer **minor units** (paise) to avoid floating point money
bugs. `50000` = Rs 500. The frontend formats with Indian digit grouping.

## Where each field is used

| Field | Rule engine | Payout | UI |
|---|---|---|---|
| `zone` | must equal event zone | - | shown |
| `threshold` | `event.value >= threshold` | - | shown |
| `payout_amount_minor` | `amount = payout x payable_days` | converted to USD | shown |
| `max_payouts_per_month` | cap on days already paid this month | - | shown |
| `waiting_period_hours` | `now >= starts_at + waiting` | - | shown |
| `active` | must be true | - | toggle |

## Versioning

Additive fields may appear in `1.x`. Any change to bounds, units or decision
semantics requires `schema_version: "2.0"` and a migration note, because old
policies remain in the ledger and must stay interpretable.
