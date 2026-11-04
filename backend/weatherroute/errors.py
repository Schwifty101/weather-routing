"""API error types and a DRF exception handler that gives every error the same JSON shape:

    {"detail": "<human readable message>", "code": "<machine code>", "fields": {...}?}
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class ApiError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "bad_request"
    default_detail = "Bad request."


class InvalidRequest(ApiError):
    default_code = "invalid_request"


class ForecastUnavailable(ApiError):
    default_code = "forecast_unavailable"


class LocationNotFound(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "location_not_found"


class NoRouteFound(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "no_route"


class UpstreamError(ApiError):
    """A third-party API (routing / geocoding / weather) failed or returned junk."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "upstream_error"


def _first_message(data) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            msg = _first_message(value)
            return f"{key}: {msg}" if key != "non_field_errors" else msg
    if isinstance(data, (list, tuple)) and data:
        return _first_message(data[0])
    return str(data)


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled error", exc_info=exc)
        return Response(
            {"detail": "Internal server error.", "code": "server_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, ValidationError):
        response.data = {
            "detail": _first_message(response.data),
            "code": "validation_error",
            "fields": response.data,
        }
    elif isinstance(exc, APIException):
        code = exc.get_codes()
        response.data = {
            "detail": _first_message(exc.detail),
            "code": code if isinstance(code, str) else exc.default_code,
        }
    return response
