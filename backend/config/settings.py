"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------
DEBUG = _env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "insecure-dev-key-do-not-use-in-production"
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.onrender.com")
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
if _env_bool("DJANGO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "weatherroute",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The app is stateless: no models, sessions or auth, so no database is configured.
DATABASES: dict = {}

USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# In the Docker image the built React app is copied to backend/frontend_dist and
# served from "/" by WhiteNoise, so one container serves UI and API.
FRONTEND_DIST = BASE_DIR / "frontend_dist"
if FRONTEND_DIST.is_dir():
    WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_INDEX_FILE = True

CORS_ALLOWED_ORIGINS = _env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
CORS_URLS_REGEX = r"^/api/.*$"

# --- DRF ---------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "weatherroute.errors.api_exception_handler",
    # Protects the free upstream APIs from a runaway client.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_THROTTLE_RATE", "120/min")},
    "NUM_PROXIES": int(os.environ["API_NUM_PROXIES"]) if os.environ.get("API_NUM_PROXIES") else None,
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- Weather routing ---------------------------------------------------------
# "live" talks to OSRM / Photon / Open-Meteo. "fake" uses deterministic offline providers
# (demo + tests) so the whole stack can run without network access.
PROVIDERS = os.environ.get("PROVIDERS", "live")

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io/api/")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
HTTP_USER_AGENT = "spotter-weather-routing/1.0 (assessment project)"
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "25"))

# OSRM's public server only has a car profile. Heavy trucks are slower, so durations are
# scaled by this factor. 1.0 disables the adjustment.
TRUCK_DURATION_FACTOR = float(os.environ.get("TRUCK_DURATION_FACTOR", "1.10"))
# "sustained" classifies on 10 m wind speed; "gust" classifies on the hourly gust instead.
WIND_METRIC = os.environ.get("WIND_METRIC", "sustained")
FORECAST_DAYS = int(os.environ.get("FORECAST_DAYS", "7"))
WEATHER_CACHE_SECONDS = int(os.environ.get("WEATHER_CACHE_SECONDS", "1800"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
