"""Hourly weather from Open-Meteo (free, no API key).

Units are requested directly in what the risk rules use: mph, and inches (so rain and snowfall
are inches per hour). Rain is `rain + showers`; snow is `snowfall` (inches of fresh snow per
hour). Many locations go into one request, requests are chunked and run in parallel, and each
point's series is cached so repeat searches and overlapping routes do not hit the API again.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from django.conf import settings
from django.core.cache import cache

from ..domain import HourlySeries, LatLon
from ..errors import UpstreamError
from .http import get_json, new_session

logger = logging.getLogger(__name__)

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
CHUNK_SIZE = 80  # locations per request keeps the URL comfortably short
MAX_WORKERS = 4


def _snap(point: LatLon) -> str:
    """~1 km grid; the forecast grid is much coarser, so nothing is lost."""
    return f"{point[0]:.2f},{point[1]:.2f}"


def _num(value) -> float:
    return float(value) if value is not None else 0.0


class OpenMeteoProvider:
    def __init__(self, url: str, session=None):
        self.url = url
        self.session = session or new_session()

    def series_for(self, points: Sequence[LatLon]) -> list[HourlySeries]:
        keys = [_snap(p) for p in points]
        unique = list(dict.fromkeys(keys))

        found: dict[str, HourlySeries] = {}
        missing: list[str] = []
        for key in unique:
            cached = cache.get(f"om:{key}")
            if cached is not None:
                found[key] = cached
            else:
                missing.append(key)

        chunks = [missing[i : i + CHUNK_SIZE] for i in range(0, len(missing), CHUNK_SIZE)]
        if chunks:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(chunks))) as pool:
                results = list(pool.map(self._fetch_chunk, chunks))
            for chunk, series_list in zip(chunks, results):
                for key, series in zip(chunk, series_list):
                    found[key] = series
                    cache.set(f"om:{key}", series, settings.WEATHER_CACHE_SECONDS)
        return [found[k] for k in keys]

    def _fetch_chunk(self, keys: list[str]) -> list[HourlySeries]:
        lats = ",".join(k.split(",")[0] for k in keys)
        lons = ",".join(k.split(",")[1] for k in keys)
        params = {
            "latitude": lats,
            "longitude": lons,
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "forecast_days": settings.FORECAST_DAYS,
        }
        data = get_json(self.session, self.url, params, service="Weather service", accept_statuses=(400,))
        if isinstance(data, dict):
            if data.get("error"):
                raise UpstreamError(f"Weather service error: {data.get('reason', 'unknown reason')}.")
            data = [data]
        if not isinstance(data, list) or len(data) != len(keys):
            raise UpstreamError("Weather service returned an unexpected response.")
        return [self._parse(item) for item in data]

    @staticmethod
    def _parse(item: dict) -> HourlySeries:
        try:
            hourly = item["hourly"]
            times = [
                datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() for t in hourly["time"]
            ]
            rain = [_num(a) + _num(b) for a, b in zip(hourly["rain"], hourly["showers"])]
            series = HourlySeries(
                times=times,
                wind=[_num(v) for v in hourly["wind_speed_10m"]],
                gust=[_num(v) for v in hourly["wind_gusts_10m"]],
                rain=rain,
                snow=[_num(v) for v in hourly["snowfall"]],
            )
        except (KeyError, TypeError, ValueError):
            raise UpstreamError("Weather service returned an unexpected response.") from None
        if not times or not (len(times) == len(series.wind) == len(series.rain) == len(series.snow)):
            raise UpstreamError("Weather service returned incomplete data.")
        return series
