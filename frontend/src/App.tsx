import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchHeatmap, fetchRules, planTrip } from "./api";
import { CheckpointTable } from "./components/CheckpointTable";
import type { HeatHandle } from "./components/HeatLayer";
import { ForecastSlider } from "./components/ForecastSlider";
import { MapView, type FocusTarget } from "./components/MapView";
import { PlannerForm } from "./components/PlannerForm";
import { RecommendationBanner, RouteCards } from "./components/RouteCards";
import { RulesPanel } from "./components/RulesPanel";
import { LEVELS } from "./lib/risk";
import type { HeatmapResponse, PlanRequest, PlanResponse, RiskRules } from "./types";

type HeatStatus = "idle" | "loading" | "error" | "ready";

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [heat, setHeat] = useState<HeatmapResponse | null>(null);
  const [heatStatus, setHeatStatus] = useState<HeatStatus>("idle");
  const [heatVisible, setHeatVisible] = useState(true);

  const [focus, setFocus] = useState<FocusTarget | null>(null);
  const [rules, setRules] = useState<RiskRules | null>(null);

  const heatRef = useRef<HeatHandle>(null);
  const planAbort = useRef<AbortController | null>(null);
  const heatAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchRules().then(setRules).catch(() => undefined); // purely informational
  }, []);

  const loadHeat = useCallback(async (p: PlanResponse) => {
    heatAbort.current?.abort();
    const controller = new AbortController();
    heatAbort.current = controller;
    setHeatStatus("loading");
    try {
      const data = await fetchHeatmap(p, controller.signal);
      setHeat(data);
      setHeatStatus("ready");
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setHeat(null);
      setHeatStatus("error");
    }
  }, []);

  const runPlan = useCallback(
    async (request: PlanRequest) => {
      planAbort.current?.abort();
      heatAbort.current?.abort();
      const controller = new AbortController();
      planAbort.current = controller;
      setBusy(true);
      setError(null);
      setHeat(null);
      setHeatStatus("idle");
      try {
        const result = await planTrip(request, controller.signal);
        setPlan(result);
        setSelectedId(result.recommended_route_id);
        setFocus(null);
        void loadHeat(result); // routes render immediately; the corridor forecast follows
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      } finally {
        if (planAbort.current === controller) setBusy(false);
      }
    },
    [loadHeat],
  );

  const onHour = useCallback((hour: number) => heatRef.current?.setHour(hour), []);
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? plan?.routes[0];

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="26" height="26">
            <path d="M5 21h14V11H5zm14-6h5l3 3v3h-8z" fill="currentColor" />
            <circle cx="10" cy="22" r="2.4" fill="#ef476f" />
            <circle cx="22" cy="22" r="2.4" fill="#ef476f" />
          </svg>
        </span>
        <h1>Weather-Aware Truck Routing</h1>
      </header>

      <aside className="sidebar">
        <PlannerForm busy={busy} onSubmit={runPlan} />

        {error && (
          <div className="card error" role="alert">
            {error}
          </div>
        )}

        {plan && selected && (
          <>
            <RecommendationBanner plan={plan} />
            <RouteCards plan={plan} selectedId={selected.id} onSelect={setSelectedId} />
            <CheckpointTable
              route={selected}
              focusIndex={focus?.routeId === selected.id ? focus.index : null}
              onFocus={(index) => setFocus({ routeId: selected.id, index, nonce: Date.now() })}
            />
          </>
        )}
        <RulesPanel rules={rules} />
        <footer className="foot">
          Routing © OSRM · Weather by Open-Meteo · Map © OpenStreetMap contributors, CARTO
        </footer>
      </aside>

      <main className="map-wrap">
        <MapView
          plan={plan}
          selectedId={selected?.id ?? ""}
          onSelect={setSelectedId}
          heat={heat}
          heatVisible={heatVisible}
          heatRef={heatRef}
          focus={focus}
        />
        <div className="legend card" aria-label="Risk legend">
          {LEVELS.map((l) => (
            <span key={l.key}>
              <span className="dot" style={{ background: l.color }} /> {l.label}
            </span>
          ))}
        </div>
        <ForecastSlider
          key={plan?.request.departure ?? "none"}
          status={heatStatus}
          heat={heat}
          startIso={plan?.request.departure ?? new Date().toISOString()}
          tripHours={selected ? selected.duration_s / 3600 : 0}
          visible={heatVisible}
          onToggleVisible={setHeatVisible}
          onHour={onHour}
          onRetry={() => plan && void loadHeat(plan)}
        />
        {busy && <div className="map-busy">Fetching routes and weather…</div>}
      </main>
    </div>
  );
}
