export type Level = 0 | 1 | 2 | 3 | 4;
export type LevelKey = "low" | "moderate" | "high" | "severe" | "no_travel";

export interface LocationRef {
  label: string;
  lat: number;
  lon: number;
}

export interface Checkpoint {
  index: number;
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  level: Level;
  level_label: string;
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  drivers: string[];
  note: string;
  load_rule: string | null;
  forecast_clamped: boolean;
}

export interface Segment {
  level: Level;
  from_mile: number;
  to_mile: number;
  coords: [number, number][];
}

export interface RouteSummary {
  miles_by_level: Record<LevelKey, number>;
  avg_risk: number;
  max_level: Level;
}

export interface RouteResult {
  id: string;
  name: string;
  distance_miles: number;
  duration_s: number;
  arrival: string;
  checkpoint_interval_miles: number;
  summary: RouteSummary;
  bounds: [[number, number], [number, number]];
  segments: Segment[];
  checkpoints: Checkpoint[];
  recommended: boolean;
  fastest: boolean;
  rank: number;
}

export interface PlanResponse {
  request: {
    origin: LocationRef;
    destination: LocationRef;
    departure: string;
    load_weight_lb: number;
    interval_miles: number | "auto";
  };
  recommended_route_id: string;
  recommendation: { summary: string; reasons: string[]; blocked: boolean };
  routes: RouteResult[];
  heatmap: { hours: number; spacing_miles: number; points: { lat: number; lon: number }[] };
  warnings: string[];
}

export interface HeatPoint {
  lat: number;
  lon: number;
  risk: number[];
  wind: number[];
  rain: number[];
  snow: number[];
}

export interface HeatmapResponse {
  start: string;
  hours: number;
  forecast_hours_available: number;
  points: HeatPoint[];
  /** copied from the plan response so the layer can size its blobs */
  spacing_miles: number;
}

export interface RiskRules {
  levels: { level: number; key: LevelKey; label: string }[];
  thresholds: Record<
    "wind" | "rain" | "snow",
    {
      unit: string;
      moderate_from: number;
      high_from: number;
      severe_from: number;
      no_travel_over: number;
      no_travel_inclusive: boolean;
    }
  >;
  load_rules: string[];
  recommendation_order: string[];
}

export type IntervalChoice = "auto" | 10 | 25 | 50;

export interface PlanRequest {
  origin: string | LocationRef;
  destination: string | LocationRef;
  departure: string;
  load_weight_lb: number;
  interval_miles: IntervalChoice;
}
