import { LEVELS, levelInfo } from "../lib/risk";
import type { LevelKey, RouteSummary } from "../types";

export function RiskBadge({ level, label }: { level: number; label?: string }) {
  const info = levelInfo(level);
  return (
    <span className="badge" style={{ background: info.color }}>
      {label ?? info.label}
    </span>
  );
}

/** Stacked bar: share of route miles at each risk level. */
export function RiskBar({ summary }: { summary: RouteSummary }) {
  const total = LEVELS.reduce((sum, l) => sum + summary.miles_by_level[l.key as LevelKey], 0) || 1;
  return (
    <div className="riskbar" role="img" aria-label={LEVELS.map((l) => `${l.label} ${summary.miles_by_level[l.key].toFixed(0)} miles`).join(", ")}>
      {LEVELS.map((l) => {
        const miles = summary.miles_by_level[l.key];
        if (miles <= 0) return null;
        return (
          <span
            key={l.key}
            title={`${l.label}: ${miles.toFixed(1)} mi`}
            style={{ width: `${(miles / total) * 100}%`, background: l.color }}
          />
        );
      })}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="spinner-row" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </span>
  );
}
