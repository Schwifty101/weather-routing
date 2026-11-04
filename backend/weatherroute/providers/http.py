"""Shared HTTP helper: one session, a sane User-Agent, retries on transient failures."""
from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

from ..errors import UpstreamError

logger = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return session


def get_json(
    session: requests.Session,
    url: str,
    params: dict | None = None,
    *,
    service: str,
    attempts: int = 3,
    accept_statuses: tuple[int, ...] = (),
):
    """GET `url` and return parsed JSON. Retries timeouts, 429 and 5xx with a short backoff.

    Statuses in `accept_statuses` are returned as parsed JSON instead of raising (some APIs
    put useful error bodies on 4xx responses).
    """
    last_problem = "no response"
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, params=params, timeout=settings.HTTP_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_problem = type(exc).__name__
            logger.warning("%s request failed (attempt %d): %s", service, attempt, exc)
        else:
            if resp.status_code == 200 or resp.status_code in accept_statuses:
                try:
                    return resp.json()
                except ValueError:
                    raise UpstreamError(f"{service} returned an invalid response.") from None
            last_problem = f"HTTP {resp.status_code}"
            if resp.status_code not in _RETRY_STATUSES:
                break
        if attempt < attempts:
            time.sleep(0.4 * attempt)
    raise UpstreamError(f"{service} is unavailable right now ({last_problem}). Please try again.")
