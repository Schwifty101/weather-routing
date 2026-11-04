import { useEffect, useMemo, useRef, useState } from "react";
import { addHours, formatDateTime } from "../lib/format";
import { levelInfo } from "../lib/risk";
import type { HeatmapResponse } from "../types";
import { Spinner } from "./ui";

interface Props {
  status: "idle" | "loading" | "error" | "ready";
  heat: HeatmapResponse | null;
  startIso: string;
  /** length of the selected trip, highlighted on the track */
  tripHours: number;
  visible: boolean;
  onToggleVisible: (v: boolean) => void;
  onHour: (hour: number) => void;
  onRetry: () => void;
}

const MAX_HOURS = 48;
const PLAY_HOURS_PER_SECOND = 3;

export function ForecastSlider({ status, heat, startIso, tripHours, visible, onToggleVisible, onHour, onRetry }: Props) {
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const hourRef = useRef(0);
  const ready = status === "ready" && heat != null;
  const limit = ready ? Math.min(MAX_HOURS, Math.max(1, heat.forecast_hours_available)) : MAX_HOURS;

  // Push every hour change to the map layer (imperative: no React re-render of the map).
  useEffect(() => {
    onHour(hour);
  }, [hour, heat, onHour]);

  // Play: advance by wall-clock time so speed is independent of frame rate.
  useEffect(() => {
    if (!playing || !ready) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      let next = hourRef.current + dt * PLAY_HOURS_PER_SECOND;
      if (next > limit) next = 0; // loop
      hourRef.current = next;
      setHour(next);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, ready, limit]);

  const worst = useMemo(() => {
    if (!heat) return null;
    const h = Math.min(MAX_HOURS, Math.round(hour));
    return Math.max(0, ...heat.points.map((p) => p.risk[h] ?? 0));
  }, [heat, hour]);

  const setManual = (value: number) => {
    hourRef.current = value;
    setHour(value);
  };

  const tripPct = Math.min(100, (tripHours / MAX_HOURS) * 100);
  const availPct = (limit / MAX_HOURS) * 100;
  const info = worst != null ? levelInfo(worst) : null;

  return (
    <div className="card slider-panel" role="group" aria-label="Weather forecast timeline">
      <div className="slider-top">
        <button
          type="button"
          className="play"
          disabled={!ready}
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <div className="slider-time">
          {ready ? (
            <>
              <strong>{formatDateTime(addHours(startIso, hour))}</strong>
              <span className="muted"> · +{hour.toFixed(hour % 1 === 0 ? 0 : 1)}h from departure</span>
            </>
          ) : status === "loading" ? (
            <Spinner label="Loading corridor forecast…" />
          ) : status === "error" ? (
            <span className="warning">
              Forecast heatmap unavailable.{" "}
              <button type="button" className="link" onClick={onRetry}>
                Retry
              </button>
            </span>
          ) : (
            <span className="muted">Plan a trip to see the forecast</span>
          )}
        </div>
        {info && (
          <span className="worst" title="Worst conditions anywhere in the corridor at this hour">
            <span className="dot" style={{ background: info.color }} /> Worst: {info.label}
          </span>
        )}
        <label className="toggle">
          <input type="checkbox" checked={visible} onChange={(e) => onToggleVisible(e.target.checked)} />
          Heatmap
        </label>
      </div>
      <input
        className="range"
        type="range"
        min={0}
        max={MAX_HOURS}
        step={0.25}
        value={hour}
        disabled={!ready}
        aria-label="Hours after departure"
        aria-valuetext={ready ? formatDateTime(addHours(startIso, hour)) : undefined}
        onChange={(e) => {
          setPlaying(false);
          setManual(Number(e.target.value));
        }}
        style={{ ["--trip" as string]: `${tripPct}%`, ["--avail" as string]: `${availPct}%` }}
      />
      <div className="ticks" aria-hidden="true">
        {[0, 12, 24, 36, 48].map((t) => (
          <span key={t}>{t === 0 ? "Depart" : `+${t}h`}</span>
        ))}
      </div>
      {ready && heat.forecast_hours_available < MAX_HOURS && (
        <p className="hint">The forecast covers {heat.forecast_hours_available} h from departure; later hours repeat the last one.</p>
      )}
    </div>
  );
}
