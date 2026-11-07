# Devpost Submission — RainCheck

**Repository:** `git@github.com:MOHAMMED-ABUZAR317/paypal_hackathon.git`  
**Demo URL:** (Render deployment URL — see `MANUAL_STEPS.md`)  
**YouTube Video:** (Public video under 3:10, see `MANUAL_STEPS.md` §3)  
**Team:** 6 members, branches `member-1-paypal` through `member-6-docs`, merged into `main`  
**Feature freeze:** 9 November 2026 · **Submission:** 11 November 2026  
**Deadline:** 12 November 2026, 12:00 pm PT

---

## Technological Implementation

**Skilled, non-trivial use of PayPal and AI**

- **Orders (funding):** Members fund the shared pool through PayPal Orders v2
  checkout. The flow is `POST /api/pool/fund` → approve in PayPal →
  `POST /api/pool/fund/{order_id}/capture`. Idempotency keys prevent double
  payment on retry.
- **Payouts (disbursement):** When a storm trigger fires, the rule engine
  authorises approved rows and the payout service creates a Payouts v1 batch
  with `sender_batch_id` and `sender_item_id` derived from the domain idempotency
  key. PayPal Payouts does not support INR, so amounts are converted at the
  documented demo rate `PAYOUT_INR_PER_USD=83.00`; the worker-facing ledger
  always shows the INR amount.
- **Webhooks:** A verified receiver at `POST /api/webhooks/paypal` confirms
  payout/item status before the ledger is final. Signature verification occurs
  before any state change; unknown event types are acknowledged, not guessed at.
- **AI layer (optional):** An OpenAI-compatible client (`AI_BASE_URL`,
  `AI_API_KEY`, `AI_MODEL`) is available but structurally unable to move money.
  `GET /api/ai/status` returns `can_move_money: false`. The policy parser
  calls the AI for structured output; without a key the deterministic parser
  runs and labels every response with `source: "rules"`.
- **Idempotency:** Every payout item carries a `sender_item_id` of the form
  `<event_id>:<policy_id>`. The same event captured twice credits the pool once.
- **Data feed:** Open-Meteo 24-hour precipitation per zone; a demo injector
  creates a fake event so the demo never depends on real weather.
- **Stack:** FastAPI + SQLAlchemy + SQLite (Postgres-ready), React + Vite +
  TypeScript + AG Grid. Single Docker image (Node builds UI, Python serves API +
  static build).

> **Evidence:** 140 backend tests pass, 30/30 parser evals pass, 15/15 golden
> fixtures pass, 25 requests / 84 assertions in Newman collection, secret scan
> clean on 97 files.

---

## Design

**A complete, coherent product**

- **Flow from enroll to payout:** One sentence → parse bounded policy → screen
  member → fund pool via PayPal Orders → simulate storm → rule engine decides
  → payout → receipt → audit log. Every screen has one obvious primary action.
- **Mock/sandbox labelling:** The UI and every API response surface `provider:
  "mock"` / `mock: true` / a `MOCK` badge when PayPal_MODE=mock. The demo never
  pretends mock money is real money.
- **Status badges & reason codes:** Approve / Deny / Hold For Review, each with
  exactly one reason code (`THRESHOLD_NOT_MET`, `POOL_PAUSED`,
  `WAITING_PERIOD`, `MEMBER_NOT_VERIFIED`, `HIGH_RISK_HOLD`, etc.).
- **AG Grid payout ledger:** Sticky header, 44px rows, tabular numerals right-
  aligned for money, status and reason code visible without a click. Pagination
  20 rows on dashboard, 10 on operator console.
- **Responsive design:** 1440×900 (desktop), 1024×768 (tablet), 390×844 (mobile).
  Mobile: card list instead of squeezed grid, AG Grid replaced by payout cards.
- **Accessibility:** WCAG 2.1 AA target; focus ring (`3px rgba(3,105,161,.55)`
  offset 2px); reduced motion respected; screen-reader-friendly form labels;
  skip-to-content link; captions on tables.
- **Design tokens:** CSS custom properties (`--ink`, `--rain`, `--teal`, `--mock`,
  etc.) throughout; no runtime CSS-in-JS; no UI framework beyond vanilla React.
- **Production build:** 60 modules, app chunk ~102 kB, React ~164 kB, AG Grid
  ~896 kB; `npm run build` succeeds with 0 errors.

> **Evidence:** Production frontend build succeeds; manual UI smoke against
> deployed URL passes; AG Grid page-size warning fixed; focus rings visible on
> every control; mobile receipt fits without horizontal scroll.

---

## Potential Impact

**A real problem for a real audience**

- **Persona:** Meena Kumari, a food-delivery rider in Hyderabad Central. On a
  storm day she earns zero; with RainCheck she receives ₹500 within minutes of
  the threshold being crossed.
- **Before:** Storm day means zero income, forms, proof of loss, weeks ofwaiting.
- **After:** Storm day triggers an automatic payout; no form, no proving loss,
  payment within minutes.
- **Speed:** Payment in seconds or minutes after the trigger, compared with days
  or weeks of a traditional claims process.
- **Certainty:** Workers know the rule before they join; the rule is visible and
  the receipt repeats the exact ledger numbers.
- **Dignity:** No proving loss, no arguing with an adjuster; the worker sees the
  rule in advance and the explanation after every payout.
- **Financial inclusion:** Micro-amounts (₹100/month contribution, ₹500 payout)
  open protection to people excluded from regular insurance products.
- **Resilience:** A small cushion on bad days reduces forced borrowing and missed
  repayments.
- **Transparency:** Every rule, trigger, decision, and payment sits in an
  auditable ledger.
- **Lower cost to serve:** Automation removes claim handling, the main cost in
  micro-insurance, making micro-amounts viable.

> **Evidence:** The demo shows one worker (Lakshmi Devi) go from sentence to
> paid receipt in under 3 minutes. The QA report documents 140 tests, 30 parser
> evals, 15 golden fixtures, 84 Newman assertions covering the full path:
> parse → enrol → fund → simulate → decide → pay → receipt → audit.

---

## Innovation

**Novel and different from existing ideas**

- **Parametric triggers from catastrophe finance:** The payment is released by an
  objective measurement (rainfall above a threshold), not by AI judging a claim.
- **No claim at all:** The user never submits evidence. The world's data does.
- **AI used for structure and defence, not for guessing:** AI writes the rule from
  natural language, checks for abuse, forecasts pool health, and explains
  outcomes. The deterministic engine decides; the AI cannot authorise, deny, or
  send a payout.
- **Real-time, event-driven payments:** The demo shows money moving the moment
  the world changes, which is more striking than a checkout.
- **Built-in guardrails as a feature:** Caps, idempotency, pause switch, and audit
  are shown on screen. Few hackathon projects make safety visible.
- **Reusable engine:** One trigger framework, many future event types (flight
  delays, crop events, shipping delays, platform outages).
- **Honest caveat:** Parametric insurance exists in the real world for larger
  commercial and agricultural customers. Our claim is that a conversational,
  AI-assisted, micro-payout version on PayPal is rare. We phrase it exactly
  like that — we do not say "nobody has ever done this."

> **Evidence:** The project was built by a team of six, each owning a separate
> workstream (PayPal, backend, AI, frontend, QA, docs). The parser fix (waiting
> clause no longer confused with the 24-hour rain window, 200 h now clamps to
> 168 h) was caught by QA and covered by nine new regression tests. The
> idempotency and fraud-screening logic is proven by the Newman collection and
> the Postman collection (25 requests, 84 assertions, 0 failures).

---

## Presentation

**A tight 3-minute video with one memorable moment**

- **Video beat sheet** (see `MANUAL_STEPS.md` §3):
  - 0:00–0:18 Dashboard cold open; pool split (70/20/10)
  - 0:18–0:38 Problem story (Meena)
  - 0:38–1:20 Enroll → Parse rule → Use demo worker → Confirm
  - 1:20–1:43 Fund → Create order → Capture and credit pool
  - 1:43–2:25 Operator → Simulate storm (62 mm, Hyderabad Central)
  - 2:25–2:48 Receipts → English → Hindi → Telugu
  - 2:48–3:05 Pause → simulate → Resume
  - 3:05–3:10 Close: "Rain today. Paid in seconds."
- **One memorable moment:** The simulate-storm centrepiece, where 62 mm of
  rainfall in Hyderabad Central triggers automatic payouts to approved workers
  in seconds. The judge sees the pool split update, the decision sample, and
  the receipt all in real time.
- **Hosted demo link:** The Render deployment URL (`https://raincheck-xyz.onrender.com`)
  so judges can explore the product without running anything locally.
- **Easy judging:** README that works on a clean machine (`README.md` quick-start
  section); all secrets are out of the repo; `demo-safe` branch frozen at the
  commit used for the recording.

> **Evidence:** The three-minute demo video (under 3:10, Public/Unlisted on
> YouTube) records the full enroll → fund → storm → receipt → pause flow. The
> README has been tested on a clean clone; all links are valid; the `demo-safe`
> branch is tagged at the merge commit of `main`.

---

## Judging Criteria Matrix

| Criterion | What the jury wants | What we show |
| --- | --- | --- |
| **Technological implementation** | Skilled, non-trivial use of PayPal and AI | Orders for funding, Payouts for disbursement, webhooks for status, idempotency keys, schema-validated AI output, a real data feed (Open-Meteo) |
| **Design** | A complete, coherent product | Clean flow from enroll to payout, clear states and errors, a polished ledger (AG Grid) |
| **Potential impact** | A real problem for a real audience | One named persona (Meena/Lakshmi), sourced numbers, a before and after |
| **Innovation** | Novel and different from existing ideas | Parametric triggers plus AI policy parsing plus agent guardrails |
| **Presentation** | End-to-end demo, clear pitch | Tight 3-minute video with one memorable moment; hosted demo link; README that works on a clean machine |

---

## Tools Used

- **Backend:** FastAPI, SQLAlchemy 2, Python 3.14, pytest, httpx, PayPal SDK
- **Frontend:** React 18, Vite 5, TypeScript, AG Grid 32.3.9, CSS custom properties
- **AI (optional):** OpenAI-compatible endpoint; deterministic fallback when key
  is unset; 52 tests covering valid output, aliases, retry, invalid JSON, prompt
  injection, clamping, numeric guard and fallbacks.
- **QA harness:** Postman collection (25 requests, 84 assertions), Newman run,
  15 golden fixtures (`scripts/qa_fixtures.py`), `python -m pytest` (140 passed),
  `python evals/run_evals.py` (30/30 pass), `python scripts/secret_scan.py` (clean).
- **Deployment:** Docker (`Dockerfile`, `.dockerignore`), Render blueprint
  (`render.yaml`), single Docker image (Node builds UI, Python serves API +
  static build).
- **Docs:** MkDocs / GitHub-flavoured Markdown; every doc in `docs/` directory;
  README links to all of them.

---

## What's Next (beyond the hackathon)

1. **Pilot partner:** A licensed insurer or broker who owns the risk and the
   policy; or an IRDAI regulatory sandbox application.
2. **Quality‑controlled weather feed:** IMD data with an SLA, or multiple gauges
   per zone to reduce basis risk.
3. **Reinsurance / stop‑loss:** To protect the pool from correlated shocks
   (one storm exhausting the reserve).
4. **KYC / device intelligence:** To replace the shared‑operator-key model and
   enable per‑member authentication.
5. **Multiple perils:** Extend the same engine to flood, heat‑wave, flight‑delay,
   event‑cancellation, and shipping‑delay triggers.
6. **Platform partnerships:** Gig platforms embedding the protection layer and
   routing worker payments through PayPal (Hyperwallet, Venmo).

---

*This repository is a **hackathon sandbox prototype**, not a licensed insurance
product. Payouts are simulated unless PayPal sandbox credentials are supplied.
Basis risk, pool risk and the regulatory position are disclosed in the UI and
in the documentation.*