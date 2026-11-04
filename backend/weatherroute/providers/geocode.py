"""Geocoding: Photon (OSM-based, no key, autocomplete friendly) with Nominatim as fallback."""
from __future__ import annotations

import logging
import re

from ..domain import Location
from ..errors import InvalidRequest, LocationNotFound, UpstreamError
from .http import get_json, new_session

logger = logging.getLogger(__name__)

_LATLON_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_latlon(text: str) -> Location | None:
    """Accept a literal "lat, lon" so users (and tests) can bypass geocoding."""
    m = _LATLON_RE.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InvalidRequest("Coordinates are out of range.")
    return Location(f"{lat:.4f}, {lon:.4f}", lat, lon)


class PhotonGeocoder:
    def __init__(self, url: str, session=None):
        self.url = url
        self.session = session or new_session()

    def search(self, query: str, limit: int = 5) -> list[Location]:
        data = get_json(self.session, self.url, {"q": query, "limit": limit, "lang": "en"}, service="Geocoding service")
        results = []
        for feature in data.get("features", []):
            try:
                lon, lat = feature["geometry"]["coordinates"][:2]
            except (KeyError, ValueError, TypeError):
                continue
            props = feature.get("properties", {})
            parts: list[str] = []
            for key in ("name", "street", "city", "state", "country"):
                value = props.get(key)
                if value and (not parts or parts[-1] != value):
                    parts.append(value)
            results.append(Location(", ".join(parts) or f"{lat:.4f}, {lon:.4f}", float(lat), float(lon)))
        return results


class NominatimGeocoder:
    def __init__(self, url: str, session=None):
        self.url = url
        self.session = session or new_session()

    def search(self, query: str, limit: int = 5) -> list[Location]:
        data = get_json(
            self.session, self.url, {"q": query, "format": "jsonv2", "limit": limit}, service="Geocoding service"
        )
        return [Location(item["display_name"], float(item["lat"]), float(item["lon"])) for item in data]


class Geocoder:
    """Tries each backend in turn; only moves on when one is *unavailable*, not when it is empty."""

    def __init__(self, backends: list):
        self.backends = backends

    def search(self, query: str, limit: int = 5) -> list[Location]:
        query = query.strip()
        if not query:
            return []
        literal = parse_latlon(query)
        if literal:
            return [literal]
        last_error: UpstreamError | None = None
        for backend in self.backends:
            try:
                return backend.search(query, limit)
            except UpstreamError as exc:
                logger.warning("%s failed: %s", type(backend).__name__, exc)
                last_error = exc
        raise last_error or UpstreamError("Geocoding service is unavailable.")

    def resolve(self, text: str) -> Location:
        results = self.search(text, limit=1)
        if not results:
            raise LocationNotFound(f'Could not find a location matching "{text}".')
        return results[0]
