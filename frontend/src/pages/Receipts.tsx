import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, ProviderPill, StatusPill } from "../components/Badge";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/StateBlocks";
import { useToast } from "../components/Toast";
import { api } from "../lib/api";
import { formatDate, formatMoney, safeMessage, zoneLabel } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { ExplainResponse, Receipt } from "../lib/types";

const LANGUAGES = [
  { id: "en" as const, label: "English" },
  { id: "hi" as const, label: "हिंदी" },
  { id: "te" as const, label: "తెలుగు" },
];

function guardMessage(explain: ExplainResponse | null): {
  tone: "ok" | "warn" | "info";
  title: string;
  body: string;
} {
  if (!explain) {
    return {
      tone: "info",
      title: "English original",
      body: "Generated deterministically from the ledger. No model involved.",
    };
  }
  if (explain.guard === "passed") {
    return {
      tone: "ok",
      title: "Numbers verified after translation",
      body: "Every number in the rewrite was checked against the original receipt before display.",
    };
  }
  if (explain.guard === "rejected_numeric_mismatch") {
    return {
      tone: "warn",
      title: "Rewrite rejected: a number changed",
      body: "The model's text was discarded and the English original is shown. Safety over fluency.",
    };
  }
  if (explain.guard === "ai_unavailable") {
    return {
      tone: "info",
      title: "AI unavailable",
      body: explain.note ?? "The English original is shown. No model key or provider error.",
    };
  }
  return {
    tone: "info",
    title: "Deterministic text",
    body: explain.note ?? "No model rewrite was needed.",
  };
}

export function ReceiptsPage() {
  const toast = useToast();
  const [params] = useSearchParams();
  const memberFilter = params.get("member") ?? "";
  const [search, setSearch] = useState("");
  const [tick, setTick] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [language, setLanguage] = useState<"en" | "hi" | "te">("en");
  const [explain, setExplain] = useState<ExplainResponse | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const configState = useApi(api.config, []);
  const receiptsState = useApi(
    () => api.receipts(memberFilter || undefined, 60),
    [memberFilter, tick],
  );

  const receipts: Receipt[] = useMemo(() => {
    const rows = receiptsState.data?.receipts ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) =>
        row.member_name.toLowerCase().includes(needle) ||
        row.payout_id.toLowerCase().includes(needle) ||
        row.zone.toLowerCase().includes(needle),
    );
  }, [receiptsState.data, search]);

  const selected = receipts.find((row) => row.payout_id === selectedId) ?? receipts[0] ?? null;

  useEffect(() => {
    setLanguage("en");
    setExplain(null);
    setActionError(null);
  }, [selected?.payout_id]);

  useEffect(() => {
    if (!selectedId && receipts.length > 0) {
      setSelectedId(receipts[0].payout_id);
    }
  }, [receipts, selectedId]);

  async function translate(next: "en" | "hi" | "te") {
    if (!selected) return;
    setLanguage(next);
    setActionError(null);
    if (next === "en") {
      setExplain(null);
      return;
    }
    setExplaining(true);
    try {
      const response = await api.explainReceipt(selected.payout_id, next);
      setExplain(response);
      if (response.guard === "rejected_numeric_mismatch") {
        toast.push("The rewrite changed a number and was discarded.", "error");
      } else if (response.source === "llm") {
        toast.push("Translated and number-checked.", "ok");
      } else {
        toast.push("No model output available; showing the English original.", "info");
      }
    } catch (error) {
      setActionError(safeMessage(error));
      setExplain(null);
    } finally {
      setExplaining(false);
    }
  }

  async function copyText() {
    const text = explain?.text ?? selected?.text;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast.push("Receipt copied.", "ok");
    } catch {
      toast.push("Clipboard is blocked in this browser. Select the text instead.", "error");
    }
  }

  const shownText = explain?.text ?? selected?.text ?? "";
  const guard = guardMessage(explain);
  const activeLanguage = LANGUAGES.find((item) => item.id === language)?.label ?? "English";

  if (receiptsState.loading && !receiptsState.data) {
    return (
      <>
        <PageHeader eyebrow="Receipts" title="Loading receipts…" />
        <Loading label="Reading the payout ledger" />
      </>
    );
  }

  if (receiptsState.error && !receiptsState.data) {
    return (
      <>
        <PageHeader eyebrow="Receipts" title="Receipts are unavailable" />
        <ErrorState message={receiptsState.error} onRetry={() => void receiptsState.reload()} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Worker receipts"
        title="The same numbers, in the worker's language."
        lead="Receipts are generated from the ledger, not from the model. Translation is optional and every number is checked against the original before it is shown."
        actions={
          <>
            <Badge tone="ok" dot>
              numeric guard on
            </Badge>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => {
                setTick((value) => value + 1);
                void receiptsState.reload();
              }}
            >
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </>
        }
      />

      {memberFilter ? (
        <div className="callout callout--info" style={{ marginBottom: 16 }}>
          <span className="callout__mark">i</span>
          <div>
            <strong>Filtered to one member.</strong>
            Receipts for member <span className="mono">{memberFilter}</span>. Remove the{" "}
            <span className="inline-code">?member=</span> query string to see everyone.
          </div>
        </div>
      ) : null}

      <div className="receipts-layout">
        <aside className="card card--flush">
          <div className="grid-toolbar">
            <div>
              <h2>Receipts</h2>
              <p className="card__sub">{receipts.length} shown</p>
            </div>
            <span className="spacer" />
            <label className="sr-only" htmlFor="receipt-search">
              Search receipts
            </label>
            <input
              id="receipt-search"
              className="input input--sm"
              placeholder="Search name, zone, payout id"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              style={{ minWidth: 0, width: "100%" }}
            />
          </div>
          {receipts.length === 0 ? (
            <EmptyState
              title="No receipts yet"
              hint="Simulate a storm in the operator console to create payouts and receipts."
            />
          ) : (
            <div className="receipt-list" style={{ padding: 10 }}>
              {receipts.map((row) => (
                <button
                  type="button"
                  key={row.payout_id}
                  className={`receipt-tab${selected?.payout_id === row.payout_id ? " receipt-tab--active" : ""}`}
                  onClick={() => setSelectedId(row.payout_id)}
                  aria-pressed={selected?.payout_id === row.payout_id}
                >
                  <div className="receipt-tab__top">
                    <span className="receipt-tab__name">{row.member_name}</span>
                    <strong className="small">{row.amount_display}</strong>
                  </div>
                  <span className="receipt-tab__meta">
                    {zoneLabel(row.zone, configState.data?.zones)} · {row.rainfall_mm ?? "—"} mm ·{" "}
                    {formatDate(row.created_at)}
                  </span>
                  <div className="row" style={{ marginTop: 2 }}>
                    <StatusPill status={row.status} />
                    <ProviderPill provider={row.provider} mock={row.provider === "mock"} />
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="stack">
          {!selected ? (
            <article className="card">
              <EmptyState
                title="Nothing selected"
                hint="A receipt appears here after the first payout."
              />
            </article>
          ) : (
            <>
              <article className="card">
                <div className="card__head">
                  <div>
                    <p className="eyebrow">Payout receipt</p>
                    <h2>{selected.member_name}</h2>
                    <p className="card__sub">
                      {formatMoney(selected.amount_minor)} ·{" "}
                      {zoneLabel(selected.zone, configState.data?.zones)} ·{" "}
                      {selected.rainfall_mm ?? "—"} mm measured
                    </p>
                  </div>
                  <div className="pill-row" style={{ justifyContent: "flex-end" }}>
                    <StatusPill status={selected.status} />
                    <ProviderPill
                      provider={selected.provider}
                      mock={selected.provider === "mock"}
                    />
                  </div>
                </div>

                <div className="row row--between" style={{ flexWrap: "wrap" }}>
                  <div className="receipt-lang" role="group" aria-label="Receipt language">
                    {LANGUAGES.map((item) => (
                      <button
                        type="button"
                        key={item.id}
                        className="btn btn--secondary btn--sm"
                        aria-pressed={language === item.id}
                        onClick={() => void translate(item.id)}
                        disabled={explaining}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                  <div className="row">
                    {explaining ? <span className="small muted">Translating…</span> : null}
                    <button
                      type="button"
                      className="btn btn--secondary btn--sm"
                      onClick={() => void copyText()}
                    >
                      Copy text
                    </button>
                  </div>
                </div>

                <div
                  className="receipt-text"
                  aria-live="polite"
                  lang={language === "hi" ? "hi" : language === "te" ? "te" : "en"}
                  style={{
                    marginTop: 14,
                    padding: "16px 18px",
                    borderRadius: 13,
                    background: "var(--surface-2)",
                    border: "1px solid var(--line)",
                  }}
                >
                  {shownText}
                </div>

                <div
                  className={`callout callout--${guard.tone}`}
                  style={{ marginTop: 13 }}
                  role="status"
                >
                  <span className="callout__mark">{guard.tone === "ok" ? "✓" : "i"}</span>
                  <div>
                    <strong>{guard.title}</strong>
                    {guard.body}
                  </div>
                </div>

                {actionError ? (
                  <div className="callout callout--danger" style={{ marginTop: 12 }} role="alert">
                    <span className="callout__mark">!</span>
                    <div>
                      <strong>Translation failed.</strong>
                      {actionError}
                    </div>
                  </div>
                ) : null}

                <div className="card__foot">
                  <p className="small muted">
                    Showing <strong>{activeLanguage}</strong>
                    {explain
                      ? ` · source: ${explain.source === "llm" ? "model" : "rules"}`
                      : " · source: rules"}
                  </p>
                  <span className="small muted mono">{selected.payout_id}</span>
                </div>
              </article>

              <div className="grid grid--2">
                <article className="card">
                  <div className="card__head">
                    <div>
                      <h2>Ledger facts</h2>
                      <p className="card__sub">Copied from the payout row, not the model.</p>
                    </div>
                  </div>
                  <div className="kv">
                    <div className="kv__row">
                      <span className="kv__key">Payout</span>
                      <span className="kv__value">{formatMoney(selected.amount_minor)}</span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Status</span>
                      <span className="kv__value">{selected.status}</span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Zone</span>
                      <span className="kv__value">
                        {zoneLabel(selected.zone, configState.data?.zones)}
                      </span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Rainfall</span>
                      <span className="kv__value">
                        {selected.rainfall_mm != null ? `${selected.rainfall_mm} mm` : "—"}
                      </span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Created</span>
                      <span className="kv__value">{formatDate(selected.created_at)}</span>
                    </div>
                    <div className="kv__row">
                      <span className="kv__key">Provider</span>
                      <span className="kv__value">
                        {selected.provider === "mock" ? "MOCK transport" : "PayPal sandbox"}
                      </span>
                    </div>
                  </div>
                </article>

                <article className="card">
                  <div className="card__head">
                    <div>
                      <h2>Why this is safe to translate</h2>
                  </div>
                  </div>
                  <ul className="small" style={{ margin: 0, paddingLeft: 19, lineHeight: 1.7 }}>
                    <li>The English receipt is generated deterministically from the ledger.</li>
                    <li>The model is asked to keep every number unchanged.</li>
                    <li>
                      <span className="inline-code">numbers_preserved()</span> compares the number
                      sets in code, before display.
                    </li>
                    <li>A dropped or changed number discards the rewrite and shows the original.</li>
                    <li>The model never changes the outcome, the amount or the status.</li>
                  </ul>
                </article>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
