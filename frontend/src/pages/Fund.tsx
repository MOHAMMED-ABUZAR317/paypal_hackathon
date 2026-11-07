import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, ProviderPill, StatusPill } from "../components/Badge";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { PoolSplit } from "../components/PoolSplit";
import { StatCard } from "../components/StatCard";
import { ErrorState, Loading } from "../components/StateBlocks";
import { useToast } from "../components/Toast";
import { api } from "../lib/api";
import {
  formatDate,
  formatMoney,
  formatNumber,
  safeMessage,
  zoneLabel,
} from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Contribution, FundResponse, Member, PublicConfig } from "../lib/types";

export function FundPage() {
  const toast = useToast();
  const [params] = useSearchParams();
  const [search, setSearch] = useState("");
  const [committedSearch, setCommittedSearch] = useState("");
  const [selectedId, setSelectedId] = useState(params.get("member") ?? "");
  const [amountRupees, setAmountRupees] = useState<number | "">("");
  const [order, setOrder] = useState<FundResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const amountInitialised = useRef(false);

  useEffect(() => {
    const fromQuery = params.get("member");
    if (fromQuery) setSelectedId(fromQuery);
  }, [params]);

  const configState = useApi(api.config, []);
  const config: PublicConfig | null = configState.data;

  const membersState = useApi(
    () => api.members(committedSearch || undefined, 20),
    [committedSearch],
  );
  const members: Member[] = useMemo(
    () => membersState.data?.members ?? [],
    [membersState.data],
  );

  const poolState = useApi(async () => {
    const [pool, contributions] = await Promise.all([
      api.pool(),
      api.contributions(selectedId || undefined, 20),
    ]);
    return { pool, contributions };
  }, [selectedId]);

  const memberState = useApi(
    () => (selectedId ? api.member(selectedId) : Promise.resolve(null)),
    [selectedId],
  );

  const selected = memberState.data?.member ?? members.find((row) => row.id === selectedId) ?? null;
  const pool = poolState.data?.pool.pool ?? null;
  const contributionMinor = pool?.contribution_amount_minor ?? 10_000;

  useEffect(() => {
    if (pool && !amountInitialised.current) {
      setAmountRupees(pool.contribution_amount_minor / 100);
      amountInitialised.current = true;
    }
  }, [pool]);

  async function reloadMoney() {
    await poolState.reload();
    await memberState.reload();
  }

  async function startFunding() {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    setOrder(null);
    try {
      const amountMinor =
        typeof amountRupees === "number" ? Math.round(amountRupees * 100) : undefined;
      const response = await api.fund(selected.id, amountMinor);
      setOrder(response);
      if (response.status === "COMPLETED") {
        toast.push(
          "This member already completed a contribution this month. The same order was reused.",
          "info",
        );
        await reloadMoney();
      } else if (response.mock) {
        toast.push("Mock order created. Capture it to credit the pool.", "ok");
      } else {
        toast.push("PayPal order created. Approve it, then capture.", "ok");
      }
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function capture() {
    if (!order?.order_id) return;
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.captureFunding(order.order_id);
      setOrder(response);
      toast.push("Contribution captured and split 70/20/10.", "ok");
      await reloadMoney();
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (poolState.loading && !poolState.data) {
    return (
      <>
        <PageHeader eyebrow="Funding" title="Loading the pool…" />
        <Loading label="Reading balances and contributions" />
      </>
    );
  }

  if (poolState.error && !poolState.data) {
    return (
      <>
        <PageHeader eyebrow="Funding" title="Funding is unavailable" />
        <ErrorState message={poolState.error} onRetry={() => void poolState.reload()} />
      </>
    );
  }

  if (!pool) return null;

  return (
    <>
      <PageHeader
        eyebrow="Pool funding"
        title="Top up the box that pays workers."
        lead="Contributions come in through PayPal Orders. Every rupee is split by code: 70% to the payout box, 20% to the reserve, 10% to running costs."
        actions={
          <>
            <Badge tone={config?.app.paypal.mode === "sandbox" ? "info" : "mock"} dot>
              {config?.app.paypal.mode === "sandbox"
                ? "PayPal sandbox orders"
                : "Mock orders · no real money"}
            </Badge>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void reloadMoney()}
            >
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </>
        }
      />

      <div className="grid grid--stats">
        <StatCard
          label="Payout box"
          value={formatMoney(pool.payout_balance_minor)}
          hint="Only this box pays claims."
          tone="rain"
        />
        <StatCard
          label="Reserve"
          value={formatMoney(pool.reserve_balance_minor)}
          hint="Untouched unless the payout box runs short."
          tone="warn"
        />
        <StatCard
          label="Contribution"
          value={formatMoney(pool.contribution_amount_minor)}
          hint="Default monthly contribution per worker."
        />
        <StatCard
          label="Contributions"
          value={poolState.data?.contributions.completed_total_display ?? "Rs 0"}
          hint={`${formatNumber(
            poolState.data?.contributions.contributions.length ?? 0,
          )} rows shown in this view`}
          tone="ok"
        />
      </div>

      <section className="section grid grid--main">
        <div className="stack">
          <article className="card">
            <div className="card__head">
              <div>
                <h2>1 · Choose a worker</h2>
                <p className="card__sub">
                  Contributions are recorded against a member, so the ledger can show who funded
                  the pool.
                </p>
              </div>
              <Badge tone="neutral">{members.length} shown</Badge>
            </div>

            <form
              className="row"
              onSubmit={(event) => {
                event.preventDefault();
                setCommittedSearch(search.trim());
              }}
            >
              <div className="field" style={{ flex: 1, minWidth: 190 }}>
                <label className="sr-only" htmlFor="member-search">
                  Search members
                </label>
                <input
                  id="member-search"
                  className="input"
                  placeholder="Search name or email"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              <button type="submit" className="btn btn--secondary">
                Search
              </button>
            </form>

            {membersState.loading ? (
              <Loading label="Finding members" />
            ) : members.length === 0 ? (
              <p className="small muted" style={{ marginTop: 12 }}>
                No members match that search. Try the demo persona: Meena.
              </p>
            ) : (
              <div className="receipt-list" style={{ marginTop: 12, maxHeight: 300 }}>
                {members.map((row) => (
                  <button
                    type="button"
                    key={row.id}
                    className={`receipt-tab${selectedId === row.id ? " receipt-tab--active" : ""}`}
                    onClick={() => {
                      setSelectedId(row.id);
                      setOrder(null);
                      setActionError(null);
                    }}
                    aria-pressed={selectedId === row.id}
                  >
                    <div className="receipt-tab__top">
                      <span className="receipt-tab__name">{row.name}</span>
                      <StatusPill status={row.status} />
                    </div>
                    <span className="receipt-tab__meta">
                      {row.email} · {zoneLabel(row.zone, config?.zones)}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {selected ? (
              <div className="callout callout--info" style={{ marginTop: 13 }}>
                <span className="callout__mark">i</span>
                <div>
                  <strong>{selected.name} selected</strong>
                  {selected.paypal_email} · {zoneLabel(selected.zone, config?.zones)} ·{" "}
                  {selected.verified ? "verified" : "unverified"}
                  {memberState.data?.pledge_display
                    ? ` · cover ${memberState.data.pledge_display}`
                    : ""}
                </div>
              </div>
            ) : (
              <div className="callout callout--warn" style={{ marginTop: 13 }}>
                <span className="callout__mark">!</span>
                <div>
                  <strong>Pick a member first.</strong>
                  The PayPal order needs a member id for the contribution ledger.
                </div>
              </div>
            )}
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>2 · Create and capture a PayPal order</h2>
                <p className="card__sub">
                  One contribution per member, month and amount. Repeating the same request is
                  idempotent.
                </p>
              </div>
              <ProviderPill
                provider={config?.app.paypal.mode === "sandbox" ? "paypal" : "mock"}
                mock={config?.app.paypal.mode !== "sandbox"}
              />
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="fund-amount">Amount (₹)</label>
                <input
                  id="fund-amount"
                  className="input"
                  type="number"
                  min={1}
                  step={1}
                  value={amountRupees}
                  onChange={(event) =>
                    setAmountRupees(event.target.value === "" ? "" : Number(event.target.value))
                  }
                />
                <p className="field__hint">
                  Default {formatMoney(contributionMinor)}. Minimum order Rs 1.
                </p>
              </div>
              <div className="field" style={{ alignContent: "end" }}>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void startFunding()}
                  disabled={!selected || busy}
                  aria-busy={busy}
                >
                  {busy ? "Talking to PayPal…" : "Create order"}
                </button>
              </div>
            </div>

            {actionError ? (
              <div className="callout callout--danger" style={{ marginTop: 13 }} role="alert">
                <span className="callout__mark">!</span>
                <div>
                  <strong>The order did not complete.</strong>
                  {actionError}
                </div>
              </div>
            ) : null}

            {order ? (
              <div className="callout callout--ok" style={{ marginTop: 13 }} role="status">
                <span className="callout__mark">✓</span>
                <div style={{ width: "100%" }}>
                  <strong>
                    Order {order.order_id || "(reused)"} · {order.status}
                  </strong>
                  <div className="kv" style={{ marginTop: 9, background: "white" }}>
                    <div className="kv__row">
                      <span className="kv__key">Amount</span>
                      <span className="kv__value">{formatMoney(order.amount_minor)}</span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Provider</span>
                      <span className="kv__value">
                        {order.provider} {order.mock ? "· simulated" : "· PayPal sandbox"}
                      </span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Contribution id</span>
                      <span className="kv__value mono small">{order.contribution_id}</span>
                    </div>
                  </div>

                  {order.status !== "COMPLETED" ? (
                    <div className="row" style={{ marginTop: 11 }}>
                      {order.approve_url ? (
                        <a
                          className="btn btn--secondary btn--sm"
                          href={order.approve_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Approve in PayPal
                        </a>
                      ) : null}
                      <button
                        type="button"
                        className="btn btn--primary btn--sm"
                        onClick={() => void capture()}
                        disabled={busy}
                      >
                        Capture and credit the pool
                      </button>
                    </div>
                  ) : (
                    <p className="small" style={{ marginTop: 8 }}>
                      Already captured. The pool balances below are up to date.
                    </p>
                  )}
                </div>
              </div>
            ) : null}

            <div className="card__foot">
              <p className="small muted">
                <strong>Mock mode</strong> returns deterministic, sandbox-shaped ids. Nothing
                leaves the machine.
              </p>
              <Link className="link-btn" to="/operator">
                Need a storm first?
              </Link>
            </div>
          </article>
        </div>

        <aside className="stack">
          <article className="card">
            <div className="card__head">
              <div>
                <h2>Pool boxes</h2>
                <p className="card__sub">{pool.name}</p>
              </div>
            </div>
            <PoolSplit
              payoutMinor={pool.payout_balance_minor}
              reserveMinor={pool.reserve_balance_minor}
            />
            <div className="kv" style={{ marginTop: 14 }}>
              <div className="kv__row">
                <span className="kv__key">Total under management</span>
                <span className="kv__value">{pool.display.total}</span>
              </div>
              <div className="kv__row">
                <span className="kv__key">Running costs collected</span>
                <span className="kv__value">{formatMoney(pool.running_costs_minor)}</span>
              </div>
              <div className="kv__row">
                <span className="kv__key">Payouts paused</span>
                <span className="kv__value">{pool.paused ? "Yes" : "No"}</span>
              </div>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Where each rupee goes</h2>
                <p className="card__sub">Fixed in code, not by the model.</p>
              </div>
            </div>
            <div className="split-70" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="pill-row" style={{ marginTop: 9 }}>
              <Badge tone="ok">70% payout box</Badge>
              <Badge tone="warn">20% reserve</Badge>
              <Badge tone="neutral">10% running costs</Badge>
            </div>
            <p className="small muted" style={{ marginTop: 11 }}>
              The reserve is the buffer for a bad month. Running costs pay for weather data,
              hosting and operations — never for payouts.
            </p>
          </article>

          <article className="card card--flush">
            <div className="card__head" style={{ padding: "18px 18px 0" }}>
              <div>
                <h2>Recent contributions</h2>
                <p className="card__sub">
                  {selected ? `Filtered to ${selected.name}` : "All members"}
                </p>
              </div>
            </div>
            <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Provider</th>
                  </tr>
                </thead>
                <tbody>
                  {(poolState.data?.contributions.contributions ?? []).map(
                    (row: Contribution) => (
                      <tr key={row.id}>
                        <td>{formatDate(row.created_at)}</td>
                        <td className="num">{row.amount_display}</td>
                        <td>
                          <StatusPill status={row.status} />
                        </td>
                        <td>
                          <ProviderPill provider={row.provider} mock={row.mock} />
                        </td>
                      </tr>
                    ),
                  )}
                  {(poolState.data?.contributions.contributions ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={4} className="muted">
                        No contributions yet. Create the first order above.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </article>
        </aside>
      </section>
    </>
  );
}
