import { formatEta } from "../lib/format";
import type { RouteResult } from "../types";
import { RiskBadge } from "./ui";

interface Props {
  route: RouteResult;
  focusIndex: number | null;
  onFocus: (index: number) => void;
}

export function CheckpointTable({ route, focusIndex, onFocus }: Props) {
  return (
    <details className="card checkpoints" open>
      <summary>
        <h2>
          {route.name} checkpoints{" "}
          <span className="muted">
            every {route.checkpoint_interval_miles} mi · {route.checkpoints.length} points
          </span>
        </h2>
      </summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Mile</th>
              <th scope="col">ETA</th>
              <th scope="col">Risk</th>
              <th scope="col">Wind</th>
              <th scope="col">Rain</th>
              <th scope="col">Snow</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((c) => (
              <tr
                key={c.index}
                className={c.index === focusIndex ? "focused" : undefined}
                onClick={() => onFocus(c.index)}
                title={c.load_rule ? `${c.note} — ${c.load_rule}` : c.note}
              >
                <td>{c.mile.toFixed(0)}</td>
                <td>
                  {formatEta(c.eta)}
                  {c.forecast_clamped && <span title="Beyond forecast range; last forecast hour used"> *</span>}
                </td>
                <td>
                  <RiskBadge level={c.level} />
                </td>
                <td className={c.drivers.includes("wind") ? "driver" : undefined}>
                  {Math.round(c.wind_mph)}
                  <span className="muted"> g{Math.round(c.gust_mph)}</span>
                </td>
                <td className={c.drivers.includes("rain") ? "driver" : undefined}>{c.rain_in_hr.toFixed(2)}</td>
                <td className={c.drivers.includes("snow") ? "driver" : undefined}>{c.snow_in_hr.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Wind in mph (g = gust), rain and snow in in/hr. Highlighted cells drive the checkpoint's risk.</p>
    </details>
  );
}
