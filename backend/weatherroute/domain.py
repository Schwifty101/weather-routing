"""Plain data types shared across providers and the planner."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

LatLon = tuple[float, float]


@dataclass(frozen=True)
class Location:
    label: str
    lat: float
    lon: float

    @property
    def point(self) -> LatLon:
        return (self.lat, self.lon)


@dataclass(frozen=True)
class Weather:
    """Weather at one place and moment, in the units the risk rules use."""

    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass
class RawRoute:
    """A route as returned by a routing provider (before any weather work)."""

    coords: list[LatLon]
    distance_mi: float
    duration_s: float
    # (fraction of route distance, cumulative seconds) pairs from the provider's steps.
    # Lets us compute ETAs that respect fast/slow stretches instead of assuming a flat speed.
    profile: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class HourlySeries:
    """Hourly forecast for one point. All lists are aligned with `times` (UTC epoch seconds)."""

    times: list[float]
    wind: list[float]
    gust: list[float]
    rain: list[float]
    snow: list[float]

    @property
    def last_time(self) -> float:
        return self.times[-1]

    def sample(self, t: float) -> tuple[Weather, bool]:
        """Linearly interpolate the forecast at epoch time `t`.

        Returns (weather, clamped). `clamped` is True when `t` lies outside the forecast
        range and the nearest available hour was used instead.
        """
        times = self.times
        clamped = t < times[0] or t > times[-1]
        t = min(max(t, times[0]), times[-1])
        if len(times) == 1:
            return Weather(self.wind[0], self.gust[0], self.rain[0], self.snow[0]), clamped
        i = min(bisect.bisect_right(times, t) - 1, len(times) - 2)
        span = times[i + 1] - times[i]
        f = (t - times[i]) / span if span > 0 else 0.0

        def lerp(values: list[float]) -> float:
            return values[i] + (values[i + 1] - values[i]) * f

        return Weather(lerp(self.wind), lerp(self.gust), lerp(self.rain), lerp(self.snow)), clamped


@dataclass
class Providers:
    """The three external capabilities the planner needs. Swappable for tests / offline demo."""

    geocoder: object  # search(query, limit) -> list[Location]; resolve(text) -> Location
    router: object  # get_route_options(origin, dest, want) -> list[RawRoute]
    weather: object  # series_for(points) -> list[HourlySeries]
