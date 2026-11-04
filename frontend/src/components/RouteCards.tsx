import { formatDuration, formatEta, formatMiles } from "../lib/format";
import type { PlanResponse, RouteResult } from "../types";
import { RiskBar } from "./ui";

interface Props {
  plan: PlanResponse;
  selectedId: string;
  onSelect: (id: string) => void;
}

export function RecommendationBanner({ plan }: { plan: PlanResponse }) {
  const { recommendation } = plan;
  const best = plan.routes.find((r) => r.id === plan.recommended_route_id);
  return (
    <section className={`card recommendation${recommendation.blocked ? " blocked" : ""}`} aria-live="polite">
      <div className="eyebrow">{recommendation.blocked ? "No safe option at this time" : `Recommended: ${best?.name ?? ""}`}</div>
      <p className="rec-summary">{recommendation.summary}</p>
      {recommendation.reasons.length > 0 && (
        <ul className="reasons">
          {recommendation.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {plan.warnings.map((w) => (
        <p key={w} className="warning">
          {w}
        </p>
      ))}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <div className={`stat${tone ? ` ${tone}` : ""}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

function RouteCard({ route, selected, onSelect }: { route: RouteResult; selected: boolean; onSelect: () => void }) {
  const m = route.summary.miles_by_level;
  return (
    <button
      type="button"
      className={`route-card${selected ? " selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <div className="route-head">
        <span className="route-name">{route.name}</span>
        {route.recommended && <span className="tag good">Recommended</span>}
        {route.fastest && <span className="tag">Fastest</span>}
        {route.summary.max_level === 4 && <span className="tag bad">No Travel</span>}
      </div>
      <div className="route-meta">
        <strong>{formatDuration(route.duration_s)}</strong>
        <span>{formatMiles(route.distance_miles)} mi</span>
        <span>arrive {formatEta(route.arrival)}</span>
      </div>
      <RiskBar summary={route.summary} />
      <div className="stats">
        <Stat label="No Travel mi" value={formatMiles(m.no_travel)} tone={m.no_travel > 0 ? "bad" : undefined} />
        <Stat label="Severe mi" value={formatMiles(m.severe)} tone={m.severe > 0 ? "bad" : undefined} />
        <Stat label="High mi" value={formatMiles(m.high)} />
        <Stat label="Avg risk" value={`${route.summary.avg_risk.toFixed(2)}/4`} />
      </div>
    </button>
  );
}

export function RouteCards({ plan, selectedId, onSelect }: Props) {
  return (
    <section aria-label="Route options" className="routes">
      <h2>
        Routes <span className="muted">ranked best first</span>
      </h2>
      {plan.routes.map((r) => (
        <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={() => onSelect(r.id)} />
      ))}
    </section>
  );
}
