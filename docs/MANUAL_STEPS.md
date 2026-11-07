# Manual Steps — Owner-Only Actions

> These steps require a PayPal Developer account, a Render dashboard, and a
> YouTube/Devpost setup. They must be performed **after** the code freeze on
> 9 November and **before** submission on 11 November.

## 1. PayPal Developer Sandbox Setup

### 1.1 Create a PayPal Sandbox Business Account
1. Go to <https://developer.paypal.com/dashboard/applications/sandbox>.
2. Click **Create App** and give it a name (e.g. `raincheck-hackathon`).
3. Copy the **Client ID** and **Secret** — **do not commit these to the repo**.
4. In the **Webhooks** section for the new app, add a webhook URL:
   `https://<your-render-url>/api/webhooks/paypal`
5. Subscribe to these event types:
   - `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`
   - `PAYMENT.PAYOUTS-ITEM.FAILED`
   - `PAYMENT.CAPTURE.COMPLETED`
6. Copy the **Webhook ID** and paste it into your `.env`:
   ```
   PAYPAL_WEBHOOK_ID=<webhook-id>
   ```
7. Create a **personal** sandbox account (separate from the business app) that
   will receive payouts. Note its email address — you will use it as
   `PAYPAL_SENDER_EMAIL`.

### 1.2 Fill the `.env` file
Copy `.env.example` to `.env` and set the following (or export them as
environment variables). Leave placeholder values for anything you are not
configuring yet — the demo runs in mock mode without them.

| Variable | Required? | Default / Example |
| --- | --- | --- |
| `PAYPAL_MODE` | no | `mock` |
| `PAYPAL_CLIENT_ID` | only for `sandbox` mode | `<your-client-id>` |
| `PAYPAL_CLIENT_SECRET` | only for `sandbox` mode | `<your-client-secret>` |
| `PAYPAL_WEBHOOK_ID` | only for `sandbox` mode with verified webhooks | `<webhook-id>` |
| `PAYPAL_SENDER_EMAIL` | only for `sandbox` mode | `raincheck-sandbox@example.com` |
| `PAYPAL_PAYOUT_CURRENCY` | no | `USD` |
| `PAYOUT_INR_PER_USD` | no | `83.00` |
| `AI_API_KEY` | no (demo works without) | leave empty for deterministic fallback |
| `OPERATOR_API_KEY` | no (demo default: `dev-operator-key`) | change before deploying publicly |

### 1.3 Run the PayPal smoke test (member 1)
```
cd backend
python -m scripts.smoke_paypal
```
This proves one Orders checkout and one Payouts call work in sandbox mode before
the demo is recorded.

## 2. Render Deployment

### 2.1 Create the Render Blueprint
1. Log in to <https://render.com>.
2. Click **New** → **Blueprint** → select this repository (`paypal_hackathon`).
3. Render will auto-detect the `Dockerfile` and `render.yaml`.
4. Review the generated service — it should use:
   - Runtime: Docker
   - Plan: free
   - Region: singapore (or your preferred region)
   - Health check: `/api/health`
5. For every environment variable that has `sync: false` in `render.yaml`,
   Render will prompt you to enter a value. Fill in at minimum:
   - `OPERATOR_API_KEY` — choose a private key; you will paste it into the
     `/operator` console.
   - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`,
     `PAYPAL_SENDER_EMAIL` — only if you are running in `sandbox` mode.
   - `AI_API_KEY` — optional; blank = deterministic fallback.
6. Click **Create Service**. Render will build the Docker image and start the
   container.

### 2.2 Verify the deployed demo
1. Open the generated URL (e.g. `https://raincheck-xyz.onrender.com`).
2. Confirm the footer/banner says **MOCK** (or **sandbox** if you configured
   credentials).
3. Open `/operator`, paste the operator key, and press **Demo reset**. Confirm
   10,000 members.
4. Run through the full enroll → fund → simulate storm → receipt flow once.
5. If anything is broken, fix the code, then **Redeploy** from the Render dashboard.

### 2.3 Free storage warning
The free Render plan uses **ephemeral storage**. A redeploy or cold restart will
reseeding the demo from `AUTO_SEED=true` / `SEED_MEMBERS=10000`. This is
acceptable for a judged hackathon demo and is stated on stage. For persistent
data, point `DATABASE_URL` at a hosted Postgres instance.

## 3. Three-Minute YouTube Video

### 3.1 Recording Setup
1. Start from the demo baseline (PowerShell):
   ```powershell
   cd backend
   $env:AUTO_SEED="true"; $env:SEED_MEMBERS="10000"
   $env:PAYPAL_MODE="mock"; $env:POLL_INTERVAL_MINUTES="0"
   python -m uvicorn app.main:app --port 8000
   ```
2. Open `http://127.0.0.1:8000` in a clean browser window.
3. Open the operator console (`/operator`) and press **Demo reset** once.
4. Set the window to 1440×900, hide the bookmark bar, disable notifications.
5. Use OBS or Loom to record at 30 fps, microphone checked with a 10-second
   test. Keep the file under 3:10.

### 3.2 Beat Sheet (must be included in the video)
| Time | Action | On-screen |
| --- | --- | --- |
| 0:00–0:18 | Dashboard cold open; pool split (70/20/10) | "Members put ₹100/month into a pool." |
| 0:18–0:38 | Problem story (Meena) | "When it rains, she loses the day." |
| 0:38–1:20 | Enroll → Parse rule → Use demo worker → Confirm | "Lakshmi is enrolled, screened, and active." |
| 1:20–1:43 | Fund → Create order → Capture and credit pool | Mock order captured, pool split updated. |
| 1:43–2:25 | Operator → Simulate storm (62 mm, Hyderabad Central) | Decision sample, reason codes, batch summary. |
| 2:25–2:48 | Receipts → English → Hindi → Telugu | Ledger facts, language buttons, MOCK label. |
| 2:48–3:05 | Pause → simulate → Resume | Zero approvals on pause, payouts restored on resume. |
| 3:05–3:10 | Close: "Rain today. Paid in seconds." | Footer banner, product name. |

### 3.3 Upload Checklist
- [ ] Length ≤ 3:10; audio levels checked; no copyrighted music.
- [ ] First 10 seconds name the problem and the product.
- [ ] Mock/sandbox mode is visible and spoken.
- [ ] Video shows enroll → fund → storm → receipt → pause.
- [ ] Uploaded to YouTube as **Public** or **Unlisted** (not Private).
- [ ] Title: `RainCheck — rain cover that pays itself \| PayPal Payouts demo`
- [ ] Description includes the repo URL, devpost URL, and "sandbox prototype".
- [ ] Link pasted into Devpost and tested in an incognito window.

## 4. Devpost Submission

### 4.1 Devpost Text
Create the submission page using the repository. The text should be organised
by the five judging criteria (see `docs/QA_REPORT.md` §5 and the Deep Dive
document). Key elements:

- **Technological implementation:** Orders for funding, Payouts for disbursement,
  webhooks for status, idempotency keys, schema-validated AI output, a real
  data feed (Open-Meteo).
- **Design:** A complete, coherent product from enroll to payout, clear states
  and errors, a polished ledger (AG Grid).
- **Potential impact:** One named persona (Meena/Lakshmi), sourced numbers,
  a before and after (storm day → automatic payout in minutes).
- **Innovation:** Parametric triggers from catastrophe finance, AI policy parsing
  plus agent guardrails, real-time event-driven payments, built-in guardrails
  (caps, idempotency, pause switch, audit) shown on screen.
- **Presentation:** A tight 3-minute video with one memorable moment.

### 4.2 Submission Steps
1. Go to <https://devpost.com/> and start a new submission for the PayPal AI
   Hackathon.
2. Paste the Devpost text (authored in `docs/DEVPOST.md`).
3. Upload the YouTube video (Public or Unlisted).
4. Paste the repository URL (`git@github.com:MOHAMMED-ABUZAR317/paypal_hackathon.git`).
5. Paste the demo URL (the Render service URL).
6. Fill in the track/technologies fields.
7. Review and submit **before November 11, 2026**.
8. After submitting, open the page in an incognito window to confirm everything
   renders correctly.

### 4.3 Post-Submission
- Check the submission page once more for any missing fields.
- Keep the repo and Render service available until the results are announced.
- If the jury asks questions, be prepared to walk through the rule engine,
  the pause switch, and the mock/sandbox labelling.

## 5. Final Checklist (run after everything is done)

| Item | Done |
| --- | --- |
| [ ] PayPal sandbox accounts created; `.env` has Client ID / Secret / Webhook ID / Sender Email (or all values are placeholder for mock mode) | |
| [ ] Render blueprint created and service deployed; demo URL reachable | |
| [ ] Mock/sandbox mode visible on every page without scrolling | |
| [ ] All 140 backend tests pass: `python -m pytest` | |
| [ ] 30/30 parser evals pass: `python evals/run_evals.py` | |
| [ ] 15/15 golden fixtures pass: `python scripts/qa_fixtures.py` | |
| [ ] Newman collection: 25 requests / 84 assertions, 0 failures | |
| [ ] Secret scan clean: `python scripts/secret_scan.py` | |
| [ ] Production frontend build succeeds: `npm run build` | |
| [ ] Manual UI smoke against the deployed URL passes | |
| [ ] Three-minute YouTube video recorded, uploaded, and linked from Devpost | |
| [ ] Devpost submission completed before Nov 11, 12:00 pm PT | |
| [ ] `demo-safe` branch frozen at the commit used for the demo | |
| [ ] All branches pushed to origin (main, member-1..6, demo-safe) | |
| [ ] This `MANUAL_STEPS.md` reviewed and signed off | |