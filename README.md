# RainCheck — Rain Cover That Pays Itself

**Parametric income protection for India's gig workers** — AI proposes the rule, deterministic code authorises the money, PayPal moves it.

[![Tests](https://img.shields.io/badge/tests-140%20passing-0f766e)](https://github.com/MOHAMMED-ABUZAR317/paypal_hackathon/blob/main/docs/QA_REPORT.md)
[![Newman](https://img.shields.io/badge/newman-84%20assertions-0f766e)](https://github.com/MOHAMMED-ABUZAR317/paypal_hackathon/tree/main/postman)
[![Mode](https://img.shields.io/badge/PayPal-mock%20%7C%20sandbox-38bdf8)](https://github.com/MOHAMMED-ABUZAR317/paypal_hackathon/blob/main/docs/PAYPAL.md)
[![Licence](https://img.shields.io/badge/licence-MIT-0a1f2b)](LICENSE)

---
## Project Overview

RainCheck is a hackathon sandbox prototype (not a licensed insurance product) that pays gig workers automatically when an objective weather trigger crosses a pre-agreed threshold. Workers join a shared protection pool, describe their cover in plain language, and a deterministic rule engine authorises payouts — no claim form, no adjuster, no discretion.

**One-liner pitch:** Income protection for gig workers that pays out automatically the moment an objective event happens, with no claim form and no waiting.

**Live demo (mock mode, no real money):** `http://127.0.0.1:8000` or the Render-deployed URL.

---

## How It Works

```text
worker's sentence                AI (optional)               deterministic core
 ─────────────────                ─────────────               ──────────────────
 "If 50 mm of rain falls in 24h,   propose structured policy   → clamp to hard bounds
  pay me ₹500, up to 3 days a month"                                    authorise the payout
                                                                      │
                                                                      ▼
                                                                PayPal Payouts
                                                                      │
                                                                      ▼
                                                                receipt + audit log
```

1. **Describe** — one sentence in English. The parser extracts threshold, payout, cap, waiting period. An LLM can propose; without a key the deterministic parser runs.
2. **Bound** — `enforce_bounds()` clamps every value in code: 5–300 mm, ₹50–₹2000, one payout/day, 1–3 days/month, waiting 24–168 h. The model cannot widen these limits.
3. **Screen** — duplicate payout addresses, shared devices, signup velocity and unverified accounts are flagged before activation and at payout time.
4. **Trigger** — Open-Meteo's 24-hour precipitation is normalised into an event. A unique event key makes the run idempotent: replaying a storm pays nobody twice.
5. **Pay** — the rule engine returns `APPROVE`, `DENY` or `HOLD_FOR_REVIEW` with one reason code. Approved rows are batched to PayPal Payouts; the pool is spent payout-box first, then reserve, and can never go negative.
6. **Explain** — every payout produces a deterministic receipt. The optional AI layer can translate it, but a numeric guard rejects any rewrite that changes a number.

> **The AI never moves money.** It proposes and explains. Deterministic code authorises. That boundary is tested, not just claimed.

---

## Stack

| Layer | Technology |
| --- | --- |
| **Backend** | FastAPI, SQLAlchemy 2, SQLite (Postgres-ready via `DATABASE_URL`) |
| **Frontend** | React 18, Vite 5, TypeScript, AG Grid 32.3.9, CSS custom properties |
| **Deployment** | Single Docker image (Node builds UI, Python serves API + static build); `render.yaml` blueprint for Render free plan |
| **QA harness** | Postman/Newman (25 requests, 84 assertions), `pytest` (140 passing), `python evals/run_evals.py` (30/30), `python scripts/qa_fixtures.py` (15/15), `python scripts/secret_scan.py` (clean) |
| **Money** | Integer paise (1 ₹ = 100 paise); INR displayed, USD sent at configurable rate `PAYOUT_INR_PER_USD=83.00` |
| **Mode** | `PAYPAL_MODE=mock` (default, labelled simulated money) or `sandbox` (real PayPal REST calls when credentials are set) |

---

## Quick Start (Local)

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:AUTO_SEED="true"; $env:SEED_MEMBERS="10000"
$env:PAYPAL_MODE="mock"; $env:POLL_INTERVAL_MINUTES="0"
python -m uvicorn app.main:app --port 8000
```

### Frontend (second terminal)

```powershell
cd frontend
npm ci
npm run dev          # http://127.0.0.1:5173, proxies /api to :8000
```

Or build once and let FastAPI serve everything:

```powershell
cd frontend
npm ci
npm run build
# restart the backend, then open http://127.0.0.1:8000
```

### Open the app

Open `http://127.0.0.1:8000`. The operator console asks for the key; the local default is `dev-operator-key`.

**60-second demo flow:**

1. **Enroll** — keep the preset sentence, press **Parse the rule**, then **Use demo worker** → **Confirm and enroll**.
2. **Fund** — select the new worker, **Create order** → **Capture and credit the pool** (mock order, clearly labelled).
3. **Operator** — enter `dev-operator-key`, press **Simulate storm** (Hyderabad Central, 62 mm). Decision sample shows approvals, holds and denials with reason codes.
4. **Receipts** — read the worker's receipt. Without an AI key the translation buttons say they are showing the English original.
5. **Demo reset** — returns to the 10,000-member baseline; the same email can enroll again.

---

## Configuration

Copy `.env.example` to `.env` (never commit the real `.env`). See `.env.example` for all variables with safe defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PAYPAL_MODE` | `mock` | `mock` = labelled simulated money; `sandbox` = real PayPal sandbox REST calls |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | empty | Sandbox app credentials (only for `sandbox` mode) |
| `PAYPAL_WEBHOOK_ID` | empty | Enables webhook signature verification |
| `PAYPAL_SENDER_EMAIL` | `raincheck-sandbox@example.com` | Sandbox business account that sends payouts |
| `PAYOUT_INR_PER_USD` | `83.00` | Payouts are sent in USD because PayPal does not support INR |
| `OPERATOR_API_KEY` | `dev-operator-key` | Header key for operator endpoints; change before deploying |
| `AUTO_SEED` / `SEED_MEMBERS` | `true` / `10000` | Deterministic demo pool |
| `POLL_INTERVAL_MINUTES` | `5` | Live Open-Meteo poller; `0` disables it |
| `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` | OpenAI-compatible / empty / `gpt-4o-mini` | Optional AI; empty key = deterministic mode |
| `DATABASE_URL` | `sqlite:///./data/raincheck.db` | Any SQLAlchemy URL; Postgres needs `psycopg` installed |

> **Every response that uses mock money says so:** `provider: "mock"`, `mock: true`, `MOCK` badge in the UI. AI responses declare `source: "llm"` or `source: "rules"`, and the AI status endpoint returns `can_move_money: false`.

---

## Project Structure

```
raincheck/
├── backend/              # FastAPI + SQLAlchemy
│   ├── app/              # Application code
│   │   ├── main.py       # Entry point, SPA serving, health check
│   │   ├── config.py     # Environment variables (never commit secrets)
│   │   ├── models.py     # SQLAlchemy models (members, policies, pool, events, decisions, payouts, audit_log)
│   │   ├── routers/      # API endpoints (policies, pool, events, operator, ai, webhooks)
│   │   ├── services/     # Business logic
│   │   │   ├── policy_parser.py   # Deterministic parser + enforce_bounds()
│   │   │   ├── screening.py       # Fraud screening (duplicate payout, device reuse, unverified)
│   │   │   ├── rules.py           # The only code that can authorise a payout
│   │   │   ├── trigger.py         # Normalised events, idempotency, summaries
│   │   │   ├── payout_service.py  # Batches, idempotency keys, pool spend/restore
│   │   │   ├── paypal.py          # Orders + Payouts + webhook signature verification
│   │   │   ├── ai/               # Optional OpenAI-compatible layer, numeric guard, receipt translation
│   │   │   └── scheduler.py       # Open-Meteo poller, fail-closed
│   │   ├── seed.py         # Demo pool seeding (10,000 members, 6 zones, fraud ring, etc.)
│   │   └── ...
│   ├── tests/            # 140 unit/integration/API tests
│   ├── evals/            # 30 labelled parser sentences
│   ├── scripts/          # qa_fixtures.py, secret_scan.py
│   └── ...
├── frontend/             # React + Vite + TypeScript + AG Grid
│   ├── src/              # Source, design tokens in styles.css
│   │   ├── pages/        # Dashboard, Enroll, Fund, Operator, Receipts, Limits
│   │   ├── lib/          # API client, types, format helpers
│   │   └── components/   # Badges, StatCard, PoolSplit, StateBlocks, etc.
│   ├── public/           # favicon.svg, index.html
│   └── package.json
├── docs/                 # All project documentation
│   ├── ARCHITECTURE.md   # Components, data model, money flow, failure modes
│   ├── API.md            # Every endpoint with request/response examples
│   ├── POLICY_SCHEMA.md  # Frozen v1.0 policy schema and bounds
│   ├── PAYPAL.md         # Orders, Payouts, webhooks, idempotency, sandbox setup
│   ├── AI_USAGE.md       # Prompts, guardrails, eval harness, fallback behaviour
│   ├── DATA_SOURCES.md   # Open-Meteo endpoint, zones, fail-closed rules, basis risk
│   ├── QA_REPORT.md      # Test matrix, guardrail evidence, security posture, limitations
│   ├── DEMO_SCRIPT.md    # 3-minute beat sheet with pre-flight and fallbacks
│   ├── IMPACT.md         # Problem, market, unit economics, ethics, regulatory position
│   ├── DESIGN_GUIDE.md   # Tokens, typography, layout, components, accessibility, copy voice
│   ├── TEAM_BOARD.md     # Six workstreams, branches, deliverables, status
│   ├── MANUAL_STEPS.md   # Owner-only steps (PayPal, Render, video, Devpost)
│   ├── DEVPOST.md        # Submission narrative, organised by 5 judging criteria
│   ├── DEMO_SCRIPT.md    # Three-minute demo script
│   └── ...
├── Dockerfile            # Multi-stage build: Node builds UI, Python serves API + static
├── render.yaml           # Render blueprint for free Docker web service
├── .env.example          # Safe-by-default environment file (never commit real values)
├── .dockerignore         # Git-ignored paths for Docker build
├── postman/              # Newman collection (25 requests, 84 assertions)
├── fixtures/             # Golden API expectations (parse, enrollment, storm)
├── .gitignore
└── README.md             # You are here
```

---

## Branches & Workstreams

Six independent workstreams, each on its own branch, merged into `main` with `--no-ff`:

| Branch | Workstream | Headline deliverable |
| --- | --- | --- |
| `member-1-paypal` | PayPal & compliance | PayPal client, Orders/Payouts/webhooks, 15 tests, `docs/PAYPAL.md` |
| `member-2-backend` | Core backend | Models, rules, trigger, payouts, seed, API, 60+ tests |
| `member-3-ai` | AI layer | Bounded parser, advisory review, translation, evals, 52 tests |
| `member-4-frontend` | Frontend | React console, design system, AG Grid ledger, SPA serving |
| `member-5-qa` | QA & data | Newman collection, fixtures, secret scan, parser fix, QA report |
| `member-6-docs` | Docs & deploy | README, Devpost, demo script, impact, design guide, Docker/Render |

After member 6 merges, `demo-safe` is frozen at that commit — no feature work lands on it.

> **Merge protocol:** Each branch is reviewed against its definition of done by the next member. No branch merges with a failing test or a secret in the diff. Merge commits use `--no-ff` so the workstream boundary stays visible.

---

## Test Evidence

```powershell
# Backend
cd backend
python -m pytest                              # 140 passed
python evals\run_evals.py                     # 30/30 pass
python scripts\qa_fixtures.py                 # 15/15 pass

# Postman/Newman
npx --yes newman run postman/RainCheck.postman_collection.json `
  -e postman/RainCheck.postman_environment.json
# 25 requests, 84 assertions, 0 failures

# Secret scan
python scripts\secret_scan.py                 # clean, 107 files scanned
```

**Full suite coverage:** parse → enrol → fund → simulate → decide → pay → receipt → audit, plus guardrails (pause, caps, waiting period, screening, idempotency, webhook signatures, prompt injection).

---

## Documentation Index

| Document | What it covers |
| --- | --- |
| `ARCHITECTURE.md` | Components, data model, money flow, failure modes |
| `API.md` | Every endpoint with request/response examples |
| `POLICY_SCHEMA.md` | Frozen v1.0 policy schema and bounds |
| `PAYPAL.md` | Orders, Payouts, webhooks, idempotency, sandbox setup |
| `AI_USAGE.md` | Prompts, guardrails, eval harness, fallback behaviour |
| `DATA_SOURCES.md` | Open-Meteo endpoint, zones, fail-closed behaviour, basis risk |
| `QA_REPORT.md` | Test matrix, guardrail evidence, security posture, limitations, release gate |
| `DEMO_SCRIPT.md` | 3-minute beat sheet with pre-flight and fallbacks |
| `IMPACT.md` | Problem, market, unit economics, ethics, regulatory position |
| `DESIGN_GUIDE.md` | Brand, tokens, components, accessibility, copy voice |
| `TEAM_BOARD.md` | Six workstreams, branches, deliverables, status |
| `MANUAL_STEPS.md` | Everything only the account owner can do |
| `DEVPOST.md` | Submission narrative, organised by 5 criteria |
| `DESIGN_GUIDE.md` | Tokens, type, components, accessibility, copy voice |

---

## Deployment

### Docker (local)

```bash
docker build -t raincheck .
docker run --rm -p 8000:8000 \
  -e PAYPAL_MODE=mock \
  -e AUTO_SEED=true \
  -e OPERATOR_API_KEY=change-me \
  raincheck
```

### Render (free plan)

1. Log in to <https://render.com>.
2. Click **New** → **Blueprint** → select this repository.
3. Review the generated service (Docker runtime, free plan, singapore region).
4. Fill in `sync: false` env vars: at minimum `OPERATOR_API_KEY`; add `PAYPAL_CLIENT_ID`/`SECRET`/`WEBHOOK_ID`/`SENDER_EMAIL` only if running in `sandbox` mode; `AI_API_KEY` optional (blank = deterministic fallback).
5. Click **Create Service**. Render builds the Docker image and starts the container.

> **Ephemeral storage warning:** The free plan uses ephemeral SQLite inside the container, so a redeploy or cold restart reseeds the 10,000-member demo. This is acceptable for a judged hackathon demo and is stated on stage. For persistent data, point `DATABASE_URL` at a hosted Postgres instance.

### Health check

The service becomes healthy at `https://<your-url>/api/health` which returns:

```json
{"status":"ok","version":"1.0.0","env":"development","database":"ok","seeded":true,"members":10000,"paypal_mode":"mock","ai_mode":"deterministic-fallback"}
```

---

## Honest Limitations (stated in the product and on stage)

1. **Basis risk.** The grid cell may stay below threshold while a worker's street floods, or pay when their street stayed dry. Disclosed in the UI and `docs/DATA_SOURCES.md`.
2. **Forecast feed.** Open-Meteo is a forecast product, not a quality-controlled observation. Production needs IMD/contractual data, multiple gauges and a paid SLA.
3. **Community pool, not insurance.** No licence, no regulator guarantee. Pool balance can be exhausted; the rules deny rather than promise money that is not there.
4. **Mock Payouts.** Unless `PAYPAL_MODE=sandbox` and credentials are set, no real PayPal API is contacted. The UI and API label this explicitly.
5. **USD conversion.** PayPal Payouts does not support INR. The demo converts at a fixed demo rate; shows both amounts.
6. **AI is optional.** Without a key the deterministic path is used; translated receipts remain English and say why.
7. **Prototype security.** One shared operator key, in-process rate limits, SQLite and `create_all` migrations are not production controls.
8. **No KYC, sanctions screening, or licensed insurance wrapper.**

> These are stated in the product, in the UI, and in `docs/QA_REPORT.md` and `docs/IMPACT.md`. They build credibility with judges and future pilot partners.

---

## Team & Timeline

| Date | Milestone |
| --- | --- |
| 5 Nov | Repo, schema, PayPal boundary agreed |
| 6 Nov | Members 1–4 complete; full flow works locally |
| 7 Nov | Member 5 QA; member 6 docs; feature freeze candidate |
| 8 Nov | Clean-clone test, Docker build, Render deploy |
| 9 Nov | **Feature freeze**; demo-safe branch; final QA pass |
| 10 Nov | Record and upload the three-minute video |
| 11 Nov | **Devpost submission** (target) |
| 12 Nov 12:00 pm PT | Hard deadline |

**Owner-only items (after code freeze, before submission):**

- PayPal Developer app, sandbox business account and credentials
- Render account, blueprint creation and environment values
- Final read of the Devpost text and on-camera claims
- Three-minute video recording and YouTube upload
- Devpost submission and confirmation email

Exact steps: [`docs/MANUAL_STEPS.md`](MANUAL_STEPS.md)

---

## Licence

MIT — see `LICENSE`. The name, the demo data and the payout simulation are provided as-is for the hackathon. This is not an offer of insurance.

---

## Quick Navigation

- **[Local quick start](#quick-start-local)** — Run everything on your machine
- **[Configuration](#configuration)** — Environment variables and safe defaults
- **[Documentation](#documentation-index)** — List of all docs
- **[Test evidence](#test-evidence)** — One-command verification results
- **[Deployment](#deployment)** — Docker and Render instructions
- **[Limitations](#honest-limitations)** — Disclosed risks and boundaries
- **[Team](#team--timeline)** — Six workstreams and the timeline

---

*Last updated: 7 November 2026. This repository is a hackathon sandbox prototype, not a licensed insurance product. Payouts are simulated unless PayPal sandbox credentials are supplied. Basis risk, pool risk and the regulatory position are disclosed in the UI and in the documentation.*