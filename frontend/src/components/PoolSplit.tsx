import { formatMoney, percent } from "../lib/format";

export function PoolSplit({
  payoutMinor,
  reserveMinor,
  compact = false,
}: {
  payoutMinor: number;
  reserveMinor: number;
  compact?: boolean;
}) {
  const total = Math.max(1, payoutMinor + reserveMinor);
  const payoutShare = percent(payoutMinor, total);
  const reserveShare = Math.round((100 - payoutShare) * 10) / 10;

  return (
    <div className={`pool-split${compact ? " pool-split--compact" : ""}`}>
      <div
        className="pool-split__bar"
        role="img"
        aria-label={`Payout box ${payoutShare} percent, reserve ${reserveShare} percent`}
      >
        <span
          className="pool-split__payout"
          style={{ width: `${Math.max(1.5, payoutShare)}%` }}
        />
        <span
          className="pool-split__reserve"
          style={{ width: `${Math.max(1.5, reserveShare)}%` }}
        />
      </div>
      <div className="pool-split__legend">
        <div>
          <span className="dot dot--payout" aria-hidden="true" />
          <span className="pool-split__name">Payout box</span>
          <strong>{formatMoney(payoutMinor)}</strong>
          <span className="muted">{payoutShare}%</span>
        </div>
        <div>
          <span className="dot dot--reserve" aria-hidden="true" />
          <span className="pool-split__name">Reserve</span>
          <strong>{formatMoney(reserveMinor)}</strong>
          <span className="muted">{reserveShare}%</span>
        </div>
      </div>
    </div>
  );
}
