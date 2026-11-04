import { LEVELS } from "../lib/risk";
import type { RiskRules } from "../types";

type Scale = RiskRules["thresholds"]["wind"];

function band(scale: Scale, i: number): string {
  const edges = [0, scale.moderate_from, scale.high_from, scale.severe_from, scale.no_travel_over];
  const dp = scale.unit === "mph" ? 0 : edges.some((e) => e < 0.5 && e > 0) ? 2 : 1;
  const f = (n: number) => n.toFixed(dp);
  if (i === 0) return `< ${f(edges[1])}`;
  if (i === 4) return `${scale.no_travel_inclusive ? "≥" : ">"} ${f(edges[4])}`;
  // wind bands are whole mph (25–34), rain/snow bands share their boundary value (0.10–0.25)
  const upper = scale.unit === "mph" ? edges[i + 1] - 1 : edges[i + 1];
  return `${f(edges[i])} – ${f(upper)}`;
}

export function RulesPanel({ rules }: { rules: RiskRules | null }) {
  if (!rules) return null;
  return (
    <details className="card rules">
      <summary>
        <h2>Risk rules</h2>
      </summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Condition</th>
              {LEVELS.map((l) => (
                <th key={l.key} scope="col">
                  <span className="dot" style={{ background: l.color }} /> {l.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(["wind", "rain", "snow"] as const).map((name) => (
              <tr key={name}>
                <th scope="row">
                  {name[0].toUpperCase() + name.slice(1)} <span className="muted">({rules.thresholds[name].unit})</span>
                </th>
                {LEVELS.map((l) => (
                  <td key={l.key}>{band(rules.thresholds[name], l.level)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Load rules</h3>
      <ul>
        {rules.load_rules.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <h3>Route preference</h3>
      <ol>
        {rules.recommendation_order.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ol>
      <p className="hint">
        Routes with any No Travel miles rank last. Miles, risk and time are bucketed (5 mi, 0.05, 5 min) so near-ties fall
        through to the next criterion. On a shared boundary (e.g. 0.25 in/hr) the higher band applies.
      </p>
    </details>
  );
}
