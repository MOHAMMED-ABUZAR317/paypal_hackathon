# Architecture

```
React (Vite + TS + AG Grid)
        |  REST / JSON
        v
FastAPI  ──────────────────────────────────────────────
  routers/        policies, pool, events, ledger, operator, webhooks
  services/
    policy_parser   sentence -> bounded PolicyPreview (v1.0)
    ai/             LLM parser, screener, forecaster, receipt writer  (member 3)
    screening       deterministic fraud signals (advisory)
    rules           APPROVE | DENY | HOLD_FOR_REVIEW  (no AI, no network)
    trigger         normalise -> candidates -> decide -> pay -> audit
    payout_service  pool spend, PayPal batches, retries, reconciliation
    scheduler       Open-Meteo poller, fail-closed
    paypal          Orders, Payouts, webhook signature verification
  models/           members, policies, pools, events, decisions, payouts,
                    contributions, audit_log
        |
        v
SQLite (local/demo)  or  Postgres (hosted)
```

## The one invariant that matters

**AI never moves money.** The AI layer can only return a *proposal* (a policy
object passing schema validation) or an *advisory* score. `services/rules.py`
is pure deterministic Python with no network or database writes, and
`services/paypal.py` is only called by `payout_service` after a rule engine
`APPROVE`. A test asserts that the AI package does not import the PayPal client.

## Decision order (fixed, explainable)

| # | Check | Outcome on failure | Reason code |
|---|---|---|---|
| 1 | Pool pause switch | DENY | `POOL_PAUSED` |
| 2 | Policy active / window | DENY | `POLICY_INACTIVE`, `POLICY_WINDOW_CLOSED` |
| 3 | Waiting period | DENY | `WAITING_PERIOD_NOT_MET` |
| 4 | Trigger + zone match | DENY | `TRIGGER_TYPE_MISMATCH`, `ZONE_MISMATCH` |
| 5 | Member status / verification | DENY / HOLD | `MEMBER_BLOCKED`, `MEMBER_NOT_VERIFIED` |
| 6 | Threshold crossed | DENY | `THRESHOLD_NOT_MET` |
| 7 | Idempotency, daily and monthly caps | DENY | `DUPLICATE_EVENT`, `DAILY_CAP_REACHED`, `MONTHLY_CAP_REACHED` |
| 8 | Pool affordability (box then reserve) | HOLD | `POOL_INSUFFICIENT_FUNDS` |
| 9 | Advisory risk score >= 70 | HOLD | `HIGH_RISK_HOLD` |
| 10 | All clear | APPROVE | `OK` / `PARTIAL_MONTHLY_CAP` |

Holds are never silent denials: the member sees a plain-language receipt saying
a human will review it.

## Money movement

```
event arrives
  -> candidates (zone + trigger + active policy)
  -> screener (advisory score, cached per member, 4 bulk queries)
  -> rule engine per candidate
  -> APPROVE: spend_from_pool() immediately (payout box, then reserve)
             + Decision row + Payout row (status CREATED)
  -> chunked into PayPal batches of <= 500 items
  -> batch create with sender_batch_id/sender_item_id derived from
     "payout:<event_id>:<policy_id>" (idempotency)
  -> rows PENDING; mock mode settles locally and says so, sandbox mode waits
     for a verified webhook
  -> audit log entry for every step
```

The pool is debited **while** deciding, inside one transaction, so two approvals
can never overdraw the same balance. One lock per pool serialises concurrent
events.

## Database

| Table | Purpose |
|---|---|
| `pools` | balances (payout box, reserve, running costs), pause switch, contribution |
| `members` | identity, zone, verification, device/IP signals for fraud checks |
| `policies` | the frozen policy schema v1.0 + source sentence + risk flags |
| `events` | normalised triggers; `(pool_id, event_key)` is unique |
| `decisions` | one row per event x policy with outcome, reason, amount; unique pair |
| `payouts` | money owed/sent; unique idempotency key, batch/item ids, provider |
| `contributions` | PayPal Orders funding; unique key per member/month/amount |
| `audit_log` | append-only record of every operator, AI, rule and PayPal action |

## Failure handling

| Failure | Behaviour |
|---|---|
| AI returns invalid JSON | one retry, then deterministic parser, then a safe 422 |
| AI/provider outage | deterministic parser and templates keep the demo alive |
| Weather feed down | no event, no payout, `feed.unavailable` audit + operator alert |
| Duplicate event | unique `event_key` -> returns the existing event, no second payout |
| Duplicate decision | unique `(event_id, policy_id)` -> cannot happen twice |
| Pool empty | HOLD + `POOL_INSUFFICIENT_FUNDS`, logged, retryable after funding |
| PayPal batch fails | rows `FAILED` with the reason; `/operator/payouts/retry` |
| Webhook signature invalid | HTTP 400, nothing mutated |
| Operator abuse | shared key (demo), every action authenticated + audited |

## Scale notes

The seed creates 10,000 members and ~10,000 policies. A full-zone demo storm
(~2,800 candidates) is decided, paid and audited in ~1.6 s locally, including
six mock PayPal batches. Bulk fraud screening uses four aggregate queries
instead of per-member round-trips. For real scale, the event heartbeat becomes
a queue (one job per event), payouts become a worker per batch, and Postgres
replaces SQLite.
