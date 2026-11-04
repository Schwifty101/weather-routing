import type { HeatmapResponse, LocationRef, PlanRequest, PlanResponse, RiskRules } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, init);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the server. Check your connection and try again.", 0, "network");
  }
  if (!resp.ok) {
    let detail = `Request failed (${resp.status}).`;
    let code: string | undefined;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
      code = body.code;
    } catch {
      /* non-JSON error body (e.g. a proxy page) */
    }
    throw new ApiError(detail, resp.status, code);
  }
  return resp.json() as Promise<T>;
}

const postJson = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

export const searchPlaces = (q: string, signal?: AbortSignal) =>
  request<{ results: LocationRef[] }>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal });

export const planTrip = (body: PlanRequest, signal?: AbortSignal) => postJson<PlanResponse>("/api/plan", body, signal);

export const fetchHeatmap = async (
  plan: PlanResponse,
  signal?: AbortSignal,
): Promise<HeatmapResponse> => {
  const data = await postJson<Omit<HeatmapResponse, "spacing_miles">>(
    "/api/heatmap",
    {
      points: plan.heatmap.points,
      departure: plan.request.departure,
      load_weight_lb: plan.request.load_weight_lb,
    },
    signal,
  );
  return { ...data, spacing_miles: plan.heatmap.spacing_miles };
};

export const fetchRules = () => request<RiskRules>("/api/risk-rules");
