"""Deterministic offline providers.

Used by the test-suite and by `PROVIDERS=fake` so the whole app (API + UI) can be demoed and
developed without network access or API quotas. Nothing here is used in production mode.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence

from .. import geo
from ..domain import HourlySeries, LatLon, Location, Providers, RawRoute
from ..errors import LocationNotFound
from .geocode import parse_latlon

CITIES: dict[str, LatLon] = {
    "chicago": (41.8781, -87.6298),
    "denver": (39.7392, -104.9903),
    "kansas city": (39.0997, -94.5786),
    "omaha": (41.2565, -95.9345),
    "minneapolis": (44.9778, -93.2650),
    "dallas": (32.7767, -96.7970),
    "oklahoma city": (35.4676, -97.5164),
    "st. louis": (38.6270, -90.1994),
    "indianapolis": (39.7684, -86.1581),
    "salt lake city": (40.7608, -111.8910),
    "des moines": (41.5868, -93.6250),
    "cheyenne": (41.1400, -104.8202),
    "nashville": (36.1627, -86.7816),
    "atlanta": (33.7490, -84.3880),
}


class FakeGeocoder:
    def search(self, query: str, limit: int = 5) -> list[Location]:
        q = query.strip().lower()
        literal = parse_latlon(q)
        if literal:
            return [literal]
        hits = [Location(name.title(), *pt) for name, pt in CITIES.items() if q and q in name]
        return hits[:limit]

    def resolve(self, text: str) -> Location:
        hits = self.search(text, 1)
        if not hits:
            raise LocationNotFound(f'Could not find a location matching "{text}".')
        return hits[0]


class FakeRouter:
    """Three routes between the endpoints: a direct one and two that bow out to either side."""

    BULGES = (0.0, 0.10, -0.10)  # lateral bulge as a fraction of the straight-line distance
    SPEEDS_MPH = (58.0, 55.0, 52.0)

    def get_route_options(self, origin: Location, dest: Location, want: int = 3) -> list[RawRoute]:
        straight = geo.haversine_mi(origin.point, dest.point)
        heading = geo.bearing_deg(origin.point, dest.point)
        n = max(8, int(straight / 2))
        routes = []
        for bulge, speed in list(zip(self.BULGES, self.SPEEDS_MPH))[:want]:
            coords: list[LatLon] = []
            for i in range(n + 1):
                t = i / n
                base = geo.destination_point(origin.point, heading, straight * t)
                # great-circle drift is ignored: fine for a demo, and keeps the ends exact
                lateral = straight * bulge * math.sin(math.pi * t)
                coords.append(
                    geo.destination_point(base, heading + 90, abs(lateral)) if lateral >= 0
                    else geo.destination_point(base, heading - 90, abs(lateral))
                )
            coords[0], coords[-1] = origin.point, dest.point
            distance = geo.cumulative_miles(coords)[-1]
            duration = distance / speed * 3600
            routes.append(RawRoute(coords, distance, duration, [(0.0, 0.0), (1.0, duration)]))
        routes.sort(key=lambda r: r.duration_s)
        return routes


WeatherField = Callable[[float, float, float], tuple[float, float, float, float]]
"""(lat, lon, epoch_seconds) -> (wind_mph, gust_mph, rain_in_hr, snow_in_hr)"""


def storm_field(day_start: float) -> WeatherField:
    """A synthetic storm that sweeps west->east across the plains and repeats every ~4.5 days.
    Snow north of 41.5N, rain south of it."""

    def field(lat: float, lon: float, t: float) -> tuple[float, float, float, float]:
        hours = (t - day_start) / 3600.0
        cx = -112.0 + (0.4 * hours) % 45.0
        cy = 40.0 + 2.0 * math.sin(hours / 17.0)
        dx = (lon - cx) * math.cos(math.radians(lat))
        dy = lat - cy
        g = math.exp(-(dx * dx + dy * dy) / (2 * 2.2**2))
        wind = 7.0 + 48.0 * g
        precip = 0.9 * g
        snow, rain = (precip * 3.5, 0.0) if lat >= 41.5 else (0.0, precip)
        return wind, wind * 1.3, rain, snow

    return field


class FakeWeather:
    def __init__(self, field: WeatherField | None = None, start: float | None = None, hours: int = 7 * 24):
        self._field = field
        self._start = start
        self.hours = hours
        self.calls: list[int] = []  # number of points requested per call (handy in tests)

    def series_for(self, points: Sequence[LatLon]) -> list[HourlySeries]:
        self.calls.append(len(points))
        start = self._start if self._start is not None else (time.time() // 86400) * 86400
        field = self._field or storm_field(start)
        times = [start + h * 3600.0 for h in range(self.hours)]
        out = []
        for lat, lon in points:
            samples = [field(lat, lon, t) for t in times]
            out.append(
                HourlySeries(
                    times=list(times),
                    wind=[s[0] for s in samples],
                    gust=[s[1] for s in samples],
                    rain=[s[2] for s in samples],
                    snow=[s[3] for s in samples],
                )
            )
        return out


def build_fake_providers(field: WeatherField | None = None, start: float | None = None) -> Providers:
    return Providers(geocoder=FakeGeocoder(), router=FakeRouter(), weather=FakeWeather(field, start))
