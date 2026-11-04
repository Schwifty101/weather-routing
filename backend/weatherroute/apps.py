import logging

from django.apps import AppConfig
from django.conf import settings


class WeatherRouteConfig(AppConfig):
    name = "weatherroute"

    def ready(self) -> None:
        if not settings.DEBUG and settings.SECRET_KEY.startswith("insecure-dev-key"):
            logging.getLogger(__name__).warning(
                "DJANGO_SECRET_KEY is not set; using the insecure development key. Set it in production."
            )
