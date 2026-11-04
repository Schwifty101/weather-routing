"""Trip planning: turns (origin, destination, departure, load) into scored routes.

Pipeline
--------
1. Resolve origin / destination to coordinates.
2. Ask the routing provider for up to three distinct routes.
3. For each route, place checkpoints every 10 / 25 / 50 miles and compute the truck's ETA at each
   one from the provider's step durations (scaled for trucks).
4. Fetch hourly weather for every checkpoint in one batch and interpolate it at the ETA.
5. Classify each checkpoint (risk.assess) and attribute route miles to levels.
6. Rank the routes (recommend.recommend).

How miles are attributed
------------------------
A checkpoint stands for the stretch of road around it: from the midpoint to the previous
checkpoint to the midpoint to the next one (the first and last checkpoints cover half a gap plus
the route's end). Those spans tile the route exactly, so level miles always sum to the total.
"""
from __future__ import annotations

import bisect
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from django.conf import settings

from . import geo, recommend, risk
from .domain import LatLon, Location, Providers, RawRoute
from .errors import ForecastUnavailable, InvalidRequest, NoRouteFound
from .providers import get_providers
from .providers.geocode import parse_latlon

logger = logging.getLogger(__name__)

INTERVAL_CHOICES = (10, 25, 50)
HEATMAP_HOURS = 48
SEGMENT_TOLERANCE_MI = 0.03  # simplification tolerance for map polylines


def choose_interval(requested: int | str, route_miles: float) -> int:
    """Honour an explicit 10/25/50, otherwise pick by trip length so long hauls stay affordable."""
    if requested in INTERVAL_CHOICES:
        return int(requested)
    if route_miles <= 150:
        return 10
    if route_miles <= 600:
        return 25
    return 50


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _Draft:
    id: str
    name: str
    raw: RawRoute
    cum: list[float]
    length: float
    interval: int
    distances: list[float]
    points: list[LatLon]
    etas: list[float]
    duration_s: float


def _resolve(geocoder, value: dict) -> Location:
    if "text" in value:
        return geocoder.resolve(value["text"])
    label = value.get("label") or f"{value['lat']:.4f}, {value['lon']:.4f}"
    return Location(label, float(value["lat"]), float(value["lon"]))


def _time_fn(raw: RawRoute):
    """fraction of route -> seconds since departure, from the provider's step profile."""
    profile = raw.profile if len(raw.profile) >= 2 else [(0.0, 0.0), (1.0, raw.duration_s)]
    xs = [p[0] for p in profile]
    ys = [p[1] for p in profile]
    scale = raw.duration_s / ys[-1] if ys[-1] > 0 else 1.0

    def at(fraction: float) -> float:
        f = min(max(fraction, 0.0), 1.0)
        i = min(max(bisect.bisect_right(xs, f) - 1, 0), len(xs) - 2)
        span = xs[i + 1] - xs[i]
        t = (f - xs[i]) / span if span > 0 else 0.0
        return (ys[i] + (ys[i + 1] - ys[i]) * t) * scale

    return at


def _make_draft(index: int, raw: RawRoute, requested_interval, departure_ts: float) -> _Draft:
    cum = geo.cumulative_miles(raw.coords)
    length = cum[-1]
    interval = choose_interval(requested_interval, length)
    distances = geo.sample_distances(length, interval)
    points = [geo.point_at(raw.coords, cum, d) for d in distances]
    time_at = _time_fn(raw)
    factor = settings.TRUCK_DURATION_FACTOR
    etas = [departure_ts + time_at(d / length if length > 0 else 0.0) * factor for d in distances]
    return _Draft(
        id=f"route-{index + 1}",
        name=f"Route {chr(65 + index)}",
        raw=raw,
        cum=cum,
        length=length,
        interval=interval,
        distances=distances,
        points=points,
        etas=etas,
        duration_s=raw.duration_s * factor,
    )


def _spans(distances: list[float], length: float) -> list[tuple[float, float]]:
    """Mile span each checkpoint is responsible for. Spans tile [0, length]."""
    spans = []
    for i, d in enumerate(distances):
        start = 0.0 if i == 0 else (distances[i - 1] + d) / 2
        end = length if i == len(distances) - 1 else (d + distances[i + 1]) / 2
        spans.append((start, end))
    return spans


def _wind_for_risk(w) -> float:
    return w.gust_mph if settings.WIND_METRIC == "gust" else w.wind_mph


def _check_departure(departure_ts: float, now_ts: float) -> None:
    if departure_ts < now_ts - 2 * 3600:
        raise InvalidRequest("Departure time is in the past.")
    horizon = now_ts + (settings.FORECAST_DAYS - 1) * 86400
    if departure_ts > horizon:
        raise ForecastUnavailable(
            f"Departure is beyond the {settings.FORECAST_DAYS - 1}-day forecast window. Pick an earlier time."
        )


def plan_trip(
    *,
    origin: dict,
    destination: dict,
    departure: datetime,
    load_weight_lb: float,
    interval_miles: int | str = "auto",
    providers: Providers | None = None,
    now: float | None = None,
) -> dict:
    providers = providers or get_providers()
    departure_ts = departure.timestamp()
    _check_departure(departure_ts, now if now is not None else time.time())

    origin_loc = _resolve(providers.geocoder, origin)
    dest_loc = _resolve(providers.geocoder, destination)
    if geo.haversine_mi(origin_loc.point, dest_loc.point) < 0.5:
        raise InvalidRequest("Origin and destination are the same place.")

    raws = providers.router.get_route_options(origin_loc, dest_loc, want=3)
    if not raws:
        raise NoRouteFound("No drivable route was found between those locations.")
    raws = sorted(raws, key=lambda r: r.duration_s)
    drafts = [_make_draft(i, raw, interval_miles, departure_ts) for i, raw in enumerate(raws)]

    # One weather batch for every checkpoint of every route.
    all_points = [p for d in drafts for p in d.points]
    all_series = providers.weather.series_for(all_points)

    warnings: list[str] = []
    if len(drafts) < 3:
        warnings.append(f"Only {len(drafts)} distinct route option(s) were available for this trip.")

    routes_out, metrics = [], []
    offset = 0
    for draft in drafts:
        series = all_series[offset : offset + len(draft.points)]
        offset += len(draft.points)
        route_payload, route_metrics, clamped_count = _score_route(draft, series, load_weight_lb)
        routes_out.append(route_payload)
        metrics.append(route_metrics)
        if clamped_count:
            warnings.append(
                f"{draft.name}: {clamped_count} checkpoint(s) arrive after the end of the forecast; "
                "the last available forecast hour was used."
            )

    rec = recommend.recommend(metrics)
    fastest = min(metrics, key=lambda m: m.duration_s)
    for payload in routes_out:
        payload["recommended"] = payload["id"] == rec.best_id
        payload["rank"] = rec.ranking.index(payload["id"]) + 1
        payload["fastest"] = payload["id"] == fastest.route_id
    routes_out.sort(key=lambda p: p["rank"])  # best first; ids / names keep their fastest-first identity

    heat_points, spacing = geo.corridor_points([d.raw.coords for d in drafts])

    return {
        "request": {
            "origin": _loc_payload(origin_loc),
            "destination": _loc_payload(dest_loc),
            "departure": iso(departure_ts),
            "load_weight_lb": load_weight_lb,
            "interval_miles": interval_miles,
        },
        "recommended_route_id": rec.best_id,
        "recommendation": {"summary": rec.summary, "reasons": rec.reasons, "blocked": rec.blocked},
        "routes": routes_out,
        "heatmap": {
            "hours": HEATMAP_HOURS + 1,
            "spacing_miles": round(spacing, 1),
            "points": [{"lat": lat, "lon": lon} for lat, lon in heat_points],
        },
        "warnings": warnings,
    }


def _loc_payload(loc: Location) -> dict:
    return {"label": loc.label, "lat": round(loc.lat, 5), "lon": round(loc.lon, 5)}


def _score_route(draft: _Draft, series: list, load_weight_lb: float):
    checkpoints = []
    levels: list[risk.Risk] = []
    clamped_count = 0
    for i, (d, p, eta, s) in enumerate(zip(draft.distances, draft.points, draft.etas, series)):
        w, clamped = s.sample(eta)
        wind = _wind_for_risk(w)
        a = risk.assess(wind, w.rain_in_hr, w.snow_in_hr, load_weight_lb)
        levels.append(a.level)
        clamped_count += clamped
        checkpoints.append(
            {
                "index": i,
                "mile": round(d, 1),
                "lat": round(p[0], 5),
                "lon": round(p[1], 5),
                "eta": iso(eta),
                "level": int(a.level),
                "level_label": a.level.label,
                "wind_mph": round(w.wind_mph, 1),
                "gust_mph": round(w.gust_mph, 1),
                "rain_in_hr": round(w.rain_in_hr, 2),
                "snow_in_hr": round(w.snow_in_hr, 2),
                "drivers": list(a.drivers),
                "note": risk.describe(a, wind, w.rain_in_hr, w.snow_in_hr),
                "load_rule": a.load_rule,
                "forecast_clamped": bool(clamped),
            }
        )

    spans = _spans(draft.distances, draft.length)
    miles = {key: 0.0 for key in risk.LEVEL_KEYS}
    weighted = 0.0
    for level, (a, b) in zip(levels, spans):
        miles[level.key] += b - a
        weighted += int(level) * (b - a)
    avg_risk = weighted / draft.length if draft.length > 0 else 0.0

    segments = _segments(draft, levels, spans)
    lats = [p[0] for p in draft.raw.coords]
    lons = [p[1] for p in draft.raw.coords]

    payload = {
        "id": draft.id,
        "name": draft.name,
        "distance_miles": round(draft.length, 1),
        "duration_s": round(draft.duration_s),
        "arrival": iso(draft.etas[-1]),
        "checkpoint_interval_miles": draft.interval,
        "summary": {
            "miles_by_level": {k: round(v, 1) for k, v in miles.items()},
            "avg_risk": round(avg_risk, 2),
            "max_level": int(max(levels)),
        },
        "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
        "segments": segments,
        "checkpoints": checkpoints,
    }
    metrics = recommend.RouteMetrics(
        route_id=draft.id,
        name=draft.name,
        no_travel_miles=miles["no_travel"],
        severe_miles=miles["severe"],
        high_miles=miles["high"],
        avg_risk=avg_risk,
        duration_s=draft.duration_s,
    )
    return payload, metrics, clamped_count


def _segments(draft: _Draft, levels: list[risk.Risk], spans: list[tuple[float, float]]) -> list[dict]:
    """Merge neighbouring spans of equal level and slice the route geometry for each run."""
    runs: list[list] = []  # [level, start, end]
    for level, (a, b) in zip(levels, spans):
        if runs and runs[-1][0] == level:
            runs[-1][2] = b
        else:
            runs.append([level, a, b])
    out = []
    for level, a, b in runs:
        coords = geo.slice_polyline(draft.raw.coords, draft.cum, a, b)
        coords = geo.simplify(coords, SEGMENT_TOLERANCE_MI)
        out.append(
            {
                "level": int(level),
                "from_mile": round(a, 1),
                "to_mile": round(b, 1),
                "coords": [[round(lat, 5), round(lon, 5)] for lat, lon in coords],
            }
        )
    return out


def heatmap_forecast(
    *,
    points: list[LatLon],
    departure: datetime,
    load_weight_lb: float,
    providers: Providers | None = None,
    now: float | None = None,
) -> dict:
    """Risk, wind, rain and snow for each corridor point at hourly offsets 0..48h from departure.

    Unlike checkpoint scoring, this is the weather at one *clock time* everywhere (what a
    forecast map shows), not the weather the truck meets at its own ETA. Risk uses the same
    thresholds and load rules.
    """
    providers = providers or get_providers()
    departure_ts = departure.timestamp()
    _check_departure(departure_ts, now if now is not None else time.time())

    series_list = providers.weather.series_for(points)
    out_points = []
    available_hours = HEATMAP_HOURS
    for (lat, lon), series in zip(points, series_list):
        available_hours = min(available_hours, max(0, int((series.last_time - departure_ts) // 3600)))
        level, wind_v, rain_v, snow_v = [], [], [], []
        for h in range(HEATMAP_HOURS + 1):
            w, _ = series.sample(departure_ts + h * 3600)
            wind = _wind_for_risk(w)
            a = risk.assess(wind, w.rain_in_hr, w.snow_in_hr, load_weight_lb)
            level.append(int(a.level))
            wind_v.append(round(wind))
            rain_v.append(round(w.rain_in_hr, 2))
            snow_v.append(round(w.snow_in_hr, 1))
        out_points.append(
            {"lat": round(lat, 3), "lon": round(lon, 3), "risk": level, "wind": wind_v, "rain": rain_v, "snow": snow_v}
        )
    return {
        "start": iso(departure_ts),
        "hours": HEATMAP_HOURS + 1,
        "forecast_hours_available": available_hours,
        "points": out_points,
    }
