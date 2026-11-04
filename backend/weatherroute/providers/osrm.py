"""Routing via an OSRM server (public demo by default; set OSRM_BASE_URL to self-host).

OSRM returns the best route plus up to a couple of alternatives. Alternatives are often missing
on long trips, so when fewer than three distinct routes come back we ask for routes forced
through a waypoint pushed sideways from the midpoint of the main route, then keep only the ones
that are genuinely different on the ground.
"""
from __future__ import annotations

import logging

from .. import geo
from ..domain import LatLon, Location, RawRoute
from ..errors import UpstreamError
from .http import get_json, new_session

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344
# A candidate must add at least this many miles of road not shared with a kept route.
MIN_UNIQUE_MILES = 5.0
MIN_UNIQUE_FRACTION = 0.04
# Waypoint offsets as a fraction of the main route length, tried alternately left and right.
VIA_OFFSET_FRACTIONS = (0.06, 0.12, 0.20)
MAX_DETOUR_DISTANCE = 1.8  # reject via-routes more than 1.8x the main route's distance
MAX_DETOUR_DURATION = 2.0


class OSRMRouter:
    def __init__(self, base_url: str, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or new_session()

    # --- low level ---------------------------------------------------------
    def _fetch(self, waypoints: list[LatLon], alternatives: bool) -> list[RawRoute]:
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
        url = f"{self.base_url}/route/v1/driving/{path}"
        base = {"overview": "full", "geometries": "geojson", "steps": "true"}
        data = None
        # Newer OSRM accepts a numeric alternatives count; older servers only true/false.
        for alt in (("3", "true") if alternatives else ("false",)):
            data = get_json(self.session, url, {**base, "alternatives": alt}, service="Routing service",
                            accept_statuses=(400, 404, 422))
            if data.get("code") != "InvalidQuery":
                break
        code = data.get("code")
        if code in ("NoRoute", "NoSegment"):
            return []
        if code != "Ok":
            raise UpstreamError(f"Routing service error: {data.get('message') or code}.")
        return [self._parse(r) for r in data.get("routes", [])]

    @staticmethod
    def _parse(route: dict) -> RawRoute:
        coords = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
        distance_m, duration_s = float(route["distance"]), float(route["duration"])

        profile: list[tuple[float, float]] = [(0.0, 0.0)]
        dist = dur = 0.0
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                dist += float(step.get("distance", 0))
                dur += float(step.get("duration", 0))
                profile.append((dist, dur))
        if dist > 0 and dur > 0:
            profile = [(d / dist, t) for d, t in profile]
        else:
            profile = [(0.0, 0.0), (1.0, duration_s)]
        return RawRoute(coords, distance_m / METERS_PER_MILE, duration_s, profile)

    # --- public ------------------------------------------------------------
    def get_route_options(self, origin: Location, dest: Location, want: int = 3) -> list[RawRoute]:
        found = self._fetch([origin.point, dest.point], alternatives=True)
        if not found:
            return []
        kept: list[RawRoute] = []
        for cand in found:
            if _is_distinct(cand, kept):
                kept.append(cand)

        if len(kept) < want:
            kept = self._fill_with_via_routes(origin, dest, kept, want)

        kept.sort(key=lambda r: r.duration_s)
        return kept[:want]

    def _fill_with_via_routes(self, origin: Location, dest: Location, kept: list[RawRoute], want: int) -> list[RawRoute]:
        main = kept[0]
        cum = geo.cumulative_miles(main.coords)
        mid = geo.point_at(main.coords, cum, cum[-1] / 2)
        before = geo.point_at(main.coords, cum, cum[-1] * 0.45)
        after = geo.point_at(main.coords, cum, cum[-1] * 0.55)
        heading = geo.bearing_deg(before, after)

        for fraction in VIA_OFFSET_FRACTIONS:
            offset = min(120.0, max(3.0, fraction * cum[-1]))
            for side in (+1, -1):
                if len(kept) >= want:
                    return kept
                via = geo.destination_point(mid, heading + 90 * side, offset)
                try:
                    routes = self._fetch([origin.point, via, dest.point], alternatives=False)
                except UpstreamError:
                    logger.info("via-route request failed; continuing with what we have")
                    continue
                if not routes:
                    continue
                cand = routes[0]
                if cand.distance_mi > main.distance_mi * MAX_DETOUR_DISTANCE:
                    continue
                if cand.duration_s > main.duration_s * MAX_DETOUR_DURATION:
                    continue
                if _is_distinct(cand, kept):
                    kept.append(cand)
        return kept


def _is_distinct(candidate: RawRoute, kept: list[RawRoute]) -> bool:
    for other in kept:
        shared = geo.shared_fraction(other.coords, candidate.coords)
        unique_miles = candidate.distance_mi * (1.0 - shared)
        if unique_miles < max(MIN_UNIQUE_MILES, MIN_UNIQUE_FRACTION * candidate.distance_mi):
            return False
    return True
