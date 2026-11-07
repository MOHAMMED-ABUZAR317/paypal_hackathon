# RainCheck QA report

**Date:** 7 November 2026
**Build:** `member-5-qa` (feature freeze 9 November, submission 11 November)
**Environment:** Windows, Python 3.14, Node 22, FastAPI `127.0.0.1:8000`,
SQLite, `PAYPAL_MODE=mock`, `AI_API_KEY` unset (deterministic fallback)
**Verdict:** **PASS** for the sandbox prototype. No blocking defect found.

This report is evidence for the hackathon demo, not a production certification.
The prototype deliberately labels mock money and states its limitations in the
UI and in `docs/`.

---

## 1. What was tested

| Layer | Harness | Result |
| --- | --- | --- |
| Backend unit + integration | `pytest` (140 tests) | **140 passed**, 0 failed |
| Deterministic parser evals | `python evals/run_evals.py` (30 labelled sentences) | **30/30 pass** |
| Golden API fixtures | `python scripts/qa_fixtures.py` (8 parse, 4 enrollment, 3 storm) | **15/15 pass** |
| End-to-end HTTP collection | Postman/Newman (25 requests, 84 assertions) | **25/25 requests, 84/84 assertions**, 0 failed |
| Secret scan | `python scripts/secret_scan.py` | **clean**, 97 files scanned |
| Frontend production build | `npm run build` | **built**, 60 modules, 0 errors |
| Manual UI smoke | Chromium against the built SPA | **pass**, see §3 |
| Live weather adapter | `POST /api/events/poll` | fail-closed; per-zone status, no payout on feed error |

The full suite is fast: backend tests finish in about 9 seconds because the
trigger is deterministic and external HTTP is mocked.

---

## 2. Guardrails verified

Each row is asserted by a test, a fixture, or the Newman collection — not only
by inspection.

| Guardrail | Evidence |
| --- | --- |
| AI cannot move money | `GET /api/ai/status` returns `can_move_money: false`; the rule engine reads only stored policy numbers |
| Server clamps every policy | `enforce_bounds()` tests: threshold 5–300 mm, payout ₹50–₹2,000, 1/day, 1–3 days/month, waiting 24–168 h |
| Prompt injection is bounded | Eval s28–s30 and `parse/prompt-injection-is-clamped`: a "pay 999999" sentence becomes ₹2,000, never an instruction |
| Unsupported trigger rejected | Earthquake sentence returns `ok: false` and a rainfall-only explanation |
| Duplicate event key pays once | Newman "Replay the same event key": `duplicate: true`, same event id, no second payout |
| Replaying an event does not double-pay | `event_key` unique per pool; second run returns the original summary |
| Pause switch stops money | Newman "Storm while paused is denied": 0 approvals, ₹0 paid, `POOL_PAUSED` reason |
| Pool cannot go negative | `POOL_INSUFFICIENT_FUNDS` denial; payout ledger sums are capped by available balance |
| Waiting period | New policies are denied until `starts_at + waiting_period_hours`; seeded histories still pay |
| Daily and monthly caps | Rule tests exercise both `DAILY_CAP_REACHED` and `MONTHLY_CAP_REACHED` |
| Unverified accounts | Denied at payout with `MEMBER_NOT_VERIFIED`; enrollment flags `UNVERIFIED_ACCOUNT` |
| Duplicate payout destination | Sybil enrollment blocked before activation (score ≥ 80, 2+ flags) |
| High-risk payout hold | Shared device/payout address becomes `HIGH_RISK_HOLD`, not an automatic payment |
| Receipt numbers match ledger | Receipt text is generated from the payout row; AI rewrite is rejected unless every number survives |
| AI outage does not break the demo | No key: parser, receipts and forecast use deterministic fallbacks and say so |
| Mock money is labelled | `provider: "mock"`, `mock: true`, `MOCK` badge on receipts, banner in the UI |
| Webhook signature check | `tests/test_paypal.py` rejects an invalid signature and accepts a correctly signed payload |
| Idempotent order capture | Same order captured twice credits the pool once |

---

## 3. Manual UI smoke

Run against the production build served by FastAPI at `http://127.0.0.1:8000`.

| Flow | Steps | Result |
| --- | --- | --- |
| Dashboard | Load `/`; pool split, forecast, AG Grid ledger | Renders, no console errors |
| Enrollment | `/enroll` → preset sentence → **Parse the rule** → **Use demo worker** → **Confirm and enroll** | Creates Lakshmi Devi, active policy, receipt |
| Funding | `/fund` → select Lakshmi → **Create order** → **Capture and credit the pool** | Mock order captured, pool split updated |
| Operator storm | `/operator` → simulate 62 mm in Hyderabad Central | Decisions sample, reason codes, batch summary |
| Pause / resume | Operator pause → simulate → resume | Paused run approves nobody; resume restores payouts |
| Fraud demo | Operator **Fraud attempt** | Blocked sybil, score and flags visible |
| Receipts | `/receipts` → select receipt → English / हिंदी / తెలుగు | Label changes; honest "No AI key" fallback text |
| Limits | `/limits` | Hard limits, reason codes, schema and disclosures render |
| Deep links | Open `/operator` and `/receipts` directly | SPA catch-all returns the app, not a 404 |
| Unknown API | `GET /api/does-not-exist` | JSON 404, not the SPA shell |

Notes:

- AG Grid's accessibility tree is pruned in the browser tooling; the smoke test
  drove the page with DOM queries and the same HTTP calls the buttons use.
- One console warning was found during the smoke test: the operator grid's page
  size was not in its selector. Fixed by adding `[10, 20, 50, 100]`; the final
  build is clean.
- The demo persona was changed from the seeded Meena Kumari to a fresh
  **Lakshmi Devi** so the story receipt and the enrollment demo do not collide.
  `Demo reset` now removes rehearsal members, so the same email can enroll again
  and the pool returns to the 10,000-member seed baseline.

---

## 4. Defect found and fixed during QA

**Parser ambiguity: waiting period vs rainfall window.** The sentence
`"Heavy rain above 80 mm in 24 hours ... wait 200 hours"` initially returned a
24-hour waiting period because the parser matched the first duration. A worker
would have become eligible ten times too early. The parser now prefers an
explicit waiting clause, ignores `in 24 hours` / `24-hour` windows, and clamps
the result to 168 hours. Covered by nine new tests and the
`parse/waiting-clause-beats-rain-window` fixture.

No other functional defect was found. Minor fixes made during member 5:

- demo reset removes rehearsal members and restores the seed baseline;
- AG Grid page-size selector warning removed;
- receipt amount assertion accepts the app's `Rs 500.00` format;
- `.gitattributes` and SQLite WAL/SHM ignores keep the repository clean.

---

## 5. Security posture (prototype scope)

Implemented:

- operator endpoints require `X-Operator-Key`; the key is never returned by the
  public config endpoint;
- the operator key lives in `sessionStorage` in the browser, not in the bundle;
- Pydantic validation on every request; money is integer paise, never floats;
- per-IP parse/enroll rate limits and a bounded AI call timeout;
- AI output is advisory and bounded; it cannot write a payout;
- PayPal webhook signatures are verified when a webhook id is configured;
- audit log records operator actions, event processing, feed failures and
  payout states;
- no secrets in the repository (secret scan clean; `.env.example` is empty).

Explicitly **not** production-grade:

- one shared operator key, no user accounts, SSO or role separation;
- rate limiting is in-process, so it resets on restart and does not span workers;
- SQLite for the demo; PostgreSQL is the deployment target but migrations are
  `create_all` in this prototype;
- no KYC, sanctions screening, or licensed insurance wrapper;
- no CSRF token (the operator key is a header, not a cookie);
- the PayPal integration is sandbox/mock only; no live credentials were used.

---

## 6. Known limitations and disclosure

These are stated in the product and should be repeated on stage:

1. **Basis risk.** A worker can lose a day's income while the nearest grid cell
   stays below the threshold, or be paid when their street stayed dry.
2. **Forecast feed.** Open-Meteo's daily precipitation is a forecast product.
   Production needs a quality-controlled observation and a paid SLA.
3. **Community pool, not insurance.** No licence, no guarantee, no regulator
   backing. Pool balance can be exhausted; the rules deny rather than promise.
4. **Mock Payouts.** Payouts are simulated unless sandbox credentials are set.
   USD conversion uses a fixed demo rate; PayPal does not pay INR.
5. **INR display, USD send.** The pool is accounted in paise; disbursement is
   converted at `PAYOUT_INR_PER_USD`.
6. **AI is optional.** Without a key the deterministic path is used; translated
   receipts remain English and say why.
7. **Demo seed.** 10,000 synthetic members make the dashboard realistic; the
   numbers are generated, not market data.

---

## 7. Reproduce

```powershell
# backend
cd backend
python -m pytest
python evals\run_evals.py

# start the demo (mock PayPal, no live polling)
$env:AUTO_SEED="true"; $env:SEED_MEMBERS="10000"
$env:PAYPAL_MODE="mock"; $env:POLL_INTERVAL_MINUTES="0"
python -m uvicorn app.main:app --port 8000

# in a second terminal
python scripts\qa_fixtures.py
python scripts\secret_scan.py
npx --yes newman run postman\RainCheck.postman_collection.json `
  -e postman\RainCheck.postman_environment.json

# frontend build
cd frontend
npm ci
npm run build
```

The fixture runner and Newman collection both call `POST /api/operator/demo/reset`
at the end, returning the pool to its 10,000-member seed baseline.

---

## 8. Release gate

- [x] 140 backend tests pass
- [x] 30/30 parser evals pass
- [x] 15/15 golden fixtures pass
- [x] 25 requests / 84 assertions pass
- [x] secret scan clean
- [x] production frontend build succeeds
- [x] manual UI smoke pass
- [x] mock mode labelled everywhere
- [x] pause, caps, waiting period, screening and idempotency verified
- [ ] real PayPal sandbox credentials exercised (manual step for the team)
- [ ] deployed URL re-tested after Render deploy (manual step for the team)
- [ ] 3-minute demo video recorded (manual step for the team)

The three unchecked items require the account owner, not code. They are listed
with exact steps in `docs/MANUAL_STEPS.md`.
