import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge } from "./Badge";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import { MockBanner } from "./MockBanner";

const NAV = [
  { to: "/", label: "Overview", icon: "grid" as const, end: true },
  { to: "/enroll", label: "Enroll a worker", icon: "user-plus" as const },
  { to: "/fund", label: "Fund the pool", icon: "wallet" as const },
  { to: "/operator", label: "Operator console", icon: "sliders" as const },
  { to: "/receipts", label: "Receipts", icon: "receipt" as const },
  { to: "/limits", label: "Limits & safety", icon: "shield" as const },
];

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const config = useApi(api.config, []);
  const health = useApi(api.health, []);

  useEffect(() => {
    setOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const current = NAV.find((item) =>
    item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
  );

  return (
    <div className={`shell${open ? " shell--nav-open" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar__brand">
          <Link to="/" className="brand">
            <Logo size={38} />
            <span>
              <strong>RainCheck</strong>
              <small>Rain cover that pays itself</small>
            </span>
          </Link>
          <button
            type="button"
            className="sidebar__close"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
          >
            <Icon name="close" />
          </button>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav__link${isActive ? " nav__link--active" : ""}`}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__foot">
          <div className="sidebar__note">
            <strong>Rules authorise. AI explains.</strong>
            <p>
              Every payout is decided by deterministic code. The model can propose a
              policy or rewrite a receipt — it cannot move money.
            </p>
          </div>
          <p className="sidebar__version">
            Sandbox build v1.0 · schema 1.0
            <br />
            Not a licensed insurance product.
          </p>
        </div>
      </aside>

      {open ? (
        <button
          type="button"
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      ) : null}

      <div className="main">
        <MockBanner config={config.data} />

        <header className="topbar">
          <button
            type="button"
            className="topbar__menu btn btn--ghost btn--icon"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            aria-expanded={open}
          >
            <Icon name="menu" />
          </button>

          <p className="topbar__crumb">
            <span>RainCheck</span>
            <span aria-hidden="true">/</span>
            <strong>{current?.label ?? "Page"}</strong>
          </p>

          <div className="topbar__chips">
            <Badge tone={health.data ? "ok" : health.error ? "danger" : "neutral"} dot>
              {health.data
                ? `${formatNumber(health.data.members)} members`
                : health.error
                  ? "API offline"
                  : "Connecting"}
            </Badge>
            <Badge tone="ai">
              {config.data?.app.ai.enabled
                ? `AI · ${config.data.app.ai.model}`
                : "AI · rules fallback"}
            </Badge>
            <Badge tone={config.data?.app.paypal.mode === "sandbox" ? "info" : "mock"}>
              {config.data?.app.paypal.mode === "sandbox" ? "PayPal sandbox" : "Mock transport"}
            </Badge>
          </div>
        </header>

        <main id="main" className="page" tabIndex={-1}>
          {children}
        </main>

        <footer className="footer">
          <p>
            RainCheck is a hackathon prototype for a community-funded parametric pool. It is
            not insurance, not a licensed financial product, and it does not guarantee
            payouts. Basis risk is real: a storm that stops your work may not cross the
            measured threshold.{" "}
            <Link to="/limits">Read the full disclosures</Link>.
          </p>
          <p className="footer__meta">FastAPI · React · AG Grid · PayPal Orders & Payouts</p>
        </footer>
      </div>
    </div>
  );
}
