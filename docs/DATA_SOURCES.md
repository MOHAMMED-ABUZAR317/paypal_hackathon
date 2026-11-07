# Data sources and trigger assumptions

RainCheck pays on **measured rainfall**, not on a worker's report. This document
records exactly which feed is used, which number is read, and what the prototype
does when the feed is wrong or unavailable. It is deliberately short enough to
audit.

## 1. Feed

| Item | Value |
| --- | --- |
| Provider | [Open-Meteo](https://open-meteo.com/) |
| Endpoint | `https://api.open-meteo.com/v1/forecast` (override with `OPEN_METEO_BASE`) |
| Metric | `daily.precipitation_sum` |
| Unit | millimetres (mm) |
| Aggregation | 24-hour total for the local calendar day |
| Timezone | `Asia/Kolkata` (IST) |
| Forecast window | `forecast_days=1` |
| Timeout | 12 seconds per zone |
| Poll cadence | `POLL_INTERVAL_MINUTES` (0 disables the live loop) |

The exact request is:

```text
GET https://api.open-meteo.com/v1/forecast
  ?latitude=17.3850
  &longitude=78.4867
  &daily=precipitation_sum
  &timezone=Asia%2FKolkata
  &forecast_days=1
```

The response contains `daily.time[0]` and `daily.precipitation_sum[0]`. RainCheck
reads **only** `precipitation_sum[0]`. No "feels like", probability of
precipitation, or hourly maximum is used. A forecast that predicts rain but
delivers none does not pay, and a downpour that the grid misses may not pay.
That is basis risk, and it is disclosed in the UI.

## 2. Zones

Each zone is a fixed coordinate. Worker addresses are never geocoded, and the
prototype stores only the zone id on a member.

| Zone id | Display name | City | Latitude | Longitude |
| --- | --- | --- | --- | --- |
| `hyderabad-central` | Hyderabad Central | Hyderabad | 17.3850 | 78.4867 |
| `hyderabad-north` | Hyderabad North (Secunderabad) | Hyderabad | 17.4948 | 78.3996 |
| `hyderabad-south` | Hyderabad South (Charminar) | Hyderabad | 17.3433 | 78.4890 |
| `hyderabad-east` | Hyderabad East (Uppal) | Hyderabad | 17.4000 | 78.5700 |
| `hyderabad-west` | Hyderabad West (Gachibowli) | Hyderabad | 17.4100 | 78.3900 |
| `warangal` | Warangal | Warangal | 17.9689 | 79.5941 |

Coordinates live in `backend/app/constants.py` and are exposed read-only at
`GET /api/zones`.

## 3. What makes an event fire

1. The scheduler polls every zone (or the operator presses **Poll live feed**).
2. A zone below its threshold is skipped and produces no event.
3. At or above the threshold, a **normalised event** is built with the same shape
   the demo button uses:
   `zone`, `value_mm`, `days=1`, `mode=live`, `data_source=open-meteo`,
   `event_key=live:<zone>:<YYYY-MM-DD>`.
4. The deterministic rule engine evaluates every active policy in that zone.
   The event threshold is the **lowest** active policy threshold in the zone,
   defaulting to 50 mm.
5. Payouts run through the same idempotent pipeline as every other event. A
   second poll on the same day reuses the event key and pays nobody twice.

The demo never needs the network: **Simulate a storm** creates the same event
shape with `mode=simulated`. This keeps the stage demo reproducible while still
exercising the production code path.

## 4. Failure behaviour (fail closed)

| Failure | Behaviour |
| --- | --- |
| DNS / timeout / HTTP error | No event, no decision, no payout |
| Response missing `precipitation_sum` | No event; `feed.unavailable` audit entry |
| Stale or impossible value | Rejected by the normaliser; no event |
| Feed returns below threshold | `below_threshold`, no event |
| Duplicate date for a zone | `duplicate`, original summary returned |

The scheduler logs the feed error and continues with the next zone. It never
falls back to a cached sunny value. `POST /api/events/poll` shows the per-zone
result, and the operator console shows the same status.

## 5. Honest limitations

- **Forecast vs observation.** The free endpoint is a forecast product. A
  production trigger should read a quality-controlled **observation** (IMD
  station or a contractual reanalysis feed), not a forecast.
- **Grid vs street.** Open-Meteo interpolates a grid cell; a worker's street can
  flood while the cell stays below threshold.
- **One gauge per zone.** A single coordinate cannot represent a large zone.
  Production would use multiple gauges and a documented aggregation rule.
- **No SLA.** The free tier has no uptime guarantee, commercial terms, or
  historical contract. A paid plan and a fallback provider are production work.
- **Licence.** Open-Meteo data is published under CC BY 4.0 and the free API is
  intended for non-commercial use. Commercial deployment needs a paid plan and
  attribution review. This prototype is a hackathon sandbox.
- **No parametric insurance licence.** RainCheck is a community pool prototype,
  not an insurer. See `docs/IMPACT.md` and the in-app disclosures.

## 6. Verify it yourself

PowerShell:

```powershell
Invoke-RestMethod "https://api.open-meteo.com/v1/forecast?latitude=17.3850&longitude=78.4867&daily=precipitation_sum&timezone=Asia%2FKolkata&forecast_days=1"
```

Then compare with the app:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/zones
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/events/poll `
  -Headers @{ "X-Operator-Key" = "dev-operator-key" }
```

The poll response is the audit trail: one row per zone, with `status` set to
`processed`, `duplicate`, `below_threshold`, or `feed_error`.

## 7. Changing the feed

`OPEN_METEO_BASE` exists so a test or a production adapter can point at a
compatible endpoint. If you change providers, keep the normalised event contract
(`backend/app/services/trigger.py`) and update the schema note in
`docs/POLICY_SCHEMA.md`; do not let a new provider write directly to payouts.
