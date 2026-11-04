import L from "leaflet";
import { memo, useEffect, useMemo, type Ref } from "react";
import { CircleMarker, MapContainer, Marker, Pane, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { formatEta } from "../lib/format";
import { levelInfo } from "../lib/risk";
import type { HeatmapResponse, PlanResponse, RouteResult } from "../types";
import { HeatLayer, type HeatHandle } from "./HeatLayer";

export interface FocusTarget {
  routeId: string;
  index: number;
  /** changes on every request so re-focusing the same checkpoint still flies there */
  nonce: number;
}

interface Props {
  plan: PlanResponse | null;
  selectedId: string;
  onSelect: (routeId: string) => void;
  heat: HeatmapResponse | null;
  heatVisible: boolean;
  heatRef: Ref<HeatHandle>;
  focus: FocusTarget | null;
}

const US_CENTER: [number, number] = [39.5, -98.35];
const CARTO_TILES = `https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png${
  import.meta.env.VITE_CARTO_API_KEY ? `?key=${encodeURIComponent(import.meta.env.VITE_CARTO_API_KEY)}` : ""
}`;

function FitToPlan({ plan }: { plan: PlanResponse | null }) {
  const map = useMap();
  useEffect(() => {
    if (!plan) return;
    const lats = plan.routes.flatMap((r) => [r.bounds[0][0], r.bounds[1][0]]);
    const lons = plan.routes.flatMap((r) => [r.bounds[0][1], r.bounds[1][1]]);
    map.fitBounds(
      [
        [Math.min(...lats), Math.min(...lons)],
        [Math.max(...lats), Math.max(...lons)],
      ],
      { padding: [48, 48], animate: true },
    );
  }, [map, plan]);
  return null;
}

function FlyToFocus({ plan, focus }: { plan: PlanResponse | null; focus: FocusTarget | null }) {
  const map = useMap();
  useEffect(() => {
    if (!plan || !focus) return;
    const cp = plan.routes.find((r) => r.id === focus.routeId)?.checkpoints[focus.index];
    if (cp) map.flyTo([cp.lat, cp.lon], Math.max(map.getZoom(), 8), { duration: 0.6 });
  }, [map, plan, focus]);
  return null;
}

const chipIcon = (text: string, selected: boolean) =>
  L.divIcon({
    className: "",
    html: `<span class="route-chip${selected ? " selected" : ""}">${text}</span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });

const endpointIcon = (kind: "start" | "end") =>
  L.divIcon({
    className: "",
    html: `<span class="endpoint ${kind}">${kind === "start" ? "Start" : "End"}</span>`,
    iconSize: [48, 24],
    iconAnchor: [24, 12],
  });

function RouteLines({ route, selected, onSelect }: { route: RouteResult; selected: boolean; onSelect: () => void }) {
  const pane = selected ? "routes-selected" : "routes-dim";
  return (
    <>
      {/* white casing keeps the route readable over the heatmap and any basemap colour */}
      {route.segments.map((s, i) => (
        <Polyline
          key={`c${i}`}
          positions={s.coords}
          pathOptions={{ color: "#ffffff", weight: selected ? 10 : 7, opacity: selected ? 0.95 : 0.7, pane, interactive: false }}
        />
      ))}
      {route.segments.map((s, i) => (
        <Polyline
          key={`s${i}`}
          positions={s.coords}
          bubblingMouseEvents={false}
          pathOptions={{
            color: levelInfo(s.level).color,
            weight: selected ? 6 : 4,
            opacity: selected ? 1 : 0.6,
            lineCap: "butt",
            pane,
          }}
          eventHandlers={{ click: onSelect }}
        >
          <Tooltip sticky>
            {route.name} · {levelInfo(s.level).label} · miles {Math.round(s.from_mile)}–{Math.round(s.to_mile)}
          </Tooltip>
        </Polyline>
      ))}
    </>
  );
}

function MapViewInner({ plan, selectedId, onSelect, heat, heatVisible, heatRef, focus }: Props) {
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? plan?.routes[0];
  const ordered = useMemo(() => (plan ? [...plan.routes].sort((a, b) => b.rank - a.rank) : []), [plan]);

  return (
    <MapContainer center={US_CENTER} zoom={4} preferCanvas className="map" zoomControl worldCopyJump>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attribution/">CARTO</a>'
        url={CARTO_TILES}
        maxZoom={19}
      />
      <HeatLayer ref={heatRef} data={heat} visible={heatVisible} />
      <FitToPlan plan={plan} />
      <FlyToFocus plan={plan} focus={focus} />

      <Pane name="routes-dim" style={{ zIndex: 410 }} />
      <Pane name="routes-selected" style={{ zIndex: 420 }} />
      <Pane name="checkpoints" style={{ zIndex: 430 }} />

      {plan &&
        ordered.map((r) => (
          <RouteLines key={r.id} route={r} selected={r.id === selected?.id} onSelect={() => onSelect(r.id)} />
        ))}

      {plan && selected && (
        <>
          {selected.checkpoints.map((c) => (
            <CircleMarker
              key={`${selected.id}-${c.index}`}
              center={[c.lat, c.lon]}
              radius={c.level >= 3 ? 7 : 5}
              bubblingMouseEvents={false}
              pathOptions={{ pane: "checkpoints", color: "#ffffff", weight: 1.5, fillColor: levelInfo(c.level).color, fillOpacity: 1 }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <strong>
                  Mile {c.mile.toFixed(0)} · {formatEta(c.eta)}
                </strong>
                <br />
                {c.note}
                <br />
                <span className="muted">
                  wind {Math.round(c.wind_mph)} (gust {Math.round(c.gust_mph)}) mph · rain {c.rain_in_hr.toFixed(2)} · snow{" "}
                  {c.snow_in_hr.toFixed(1)} in/hr
                </span>
              </Tooltip>
            </CircleMarker>
          ))}
          {focus && focus.routeId === selected.id && selected.checkpoints[focus.index] && (
            <CircleMarker
              center={[selected.checkpoints[focus.index].lat, selected.checkpoints[focus.index].lon]}
              radius={12}
              interactive={false}
              pathOptions={{ pane: "checkpoints", color: "#073b4c", weight: 3, fill: false }}
            />
          )}
          {plan.routes.map((r, i) => {
            // spread the route letters along the route so overlapping routes don't stack chips
            const cps = r.checkpoints;
            const cp = cps[Math.min(cps.length - 1, Math.round((cps.length - 1) * (0.3 + 0.2 * (parseInt(r.id.split("-")[1], 10) - 1))))];
            return (
              <Marker
                key={`chip-${r.id}-${i}`}
                position={[cp.lat, cp.lon]}
                icon={chipIcon(r.name.replace("Route ", ""), r.id === selected.id)}
                eventHandlers={{ click: () => onSelect(r.id) }}
              />
            );
          })}
          <Marker position={[plan.request.origin.lat, plan.request.origin.lon]} icon={endpointIcon("start")} interactive={false} />
          <Marker position={[plan.request.destination.lat, plan.request.destination.lon]} icon={endpointIcon("end")} interactive={false} />
        </>
      )}
    </MapContainer>
  );
}

export const MapView = memo(MapViewInner);
