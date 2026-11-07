import { Link } from "react-router-dom";
import type { PublicConfig } from "../lib/types";

export function MockBanner({ config }: { config: PublicConfig | null }) {
  const mock = config?.app.paypal.mode !== "sandbox";
  return (
    <div className={`mock-banner${mock ? " mock-banner--mock" : " mock-banner--sandbox"}`}>
      <span className="mock-banner__tag">{mock ? "MOCK PAYOUTS" : "PAYPAL SANDBOX"}</span>
      <span className="mock-banner__text">
        {mock
          ? "Simulated PayPal transport — no real money moves."
          : "Test money only. Real PayPal sandbox API calls, no live funds."}
      </span>
      <span className="mock-banner__sep" aria-hidden="true">
        ·
      </span>
      <span className="mock-banner__text mock-banner__text--soft">
        Community pool prototype, not licensed insurance.
      </span>
      <Link className="mock-banner__link" to="/limits">
        Disclosures
      </Link>
    </div>
  );
}
