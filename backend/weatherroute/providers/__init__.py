from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from ..domain import Providers


@lru_cache(maxsize=4)
def _build(mode: str) -> Providers:
    if mode == "fake":
        from .fake import build_fake_providers

        return build_fake_providers()

    from .geocode import Geocoder, NominatimGeocoder, PhotonGeocoder
    from .openmeteo import OpenMeteoProvider
    from .osrm import OSRMRouter

    return Providers(
        geocoder=Geocoder([PhotonGeocoder(settings.PHOTON_URL), NominatimGeocoder(settings.NOMINATIM_URL)]),
        router=OSRMRouter(settings.OSRM_BASE_URL),
        weather=OpenMeteoProvider(settings.OPEN_METEO_URL),
    )


def get_providers() -> Providers:
    """The configured provider set. Built once per mode so HTTP sessions are reused."""
    return _build(settings.PROVIDERS)
