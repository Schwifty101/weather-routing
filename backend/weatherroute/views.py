from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from . import planner, risk
from .errors import InvalidRequest
from .providers import get_providers
from .serializers import HeatmapRequestSerializer, PlanRequestSerializer


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class RiskRulesView(APIView):
    """The thresholds and load rules the backend applies, so the UI can show them verbatim."""

    def get(self, request):
        return Response(risk.rules_payload())


class GeocodeView(APIView):
    """Autocomplete suggestions for the origin / destination inputs."""

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if len(query) < 3:
            raise InvalidRequest("Type at least 3 characters.")
        results = get_providers().geocoder.search(query[:200], limit=5)
        return Response(
            {"results": [{"label": r.label, "lat": round(r.lat, 5), "lon": round(r.lon, 5)} for r in results]}
        )


class PlanView(APIView):
    def post(self, request):
        ser = PlanRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        return Response(
            planner.plan_trip(
                origin=data["origin"],
                destination=data["destination"],
                departure=data["departure"],
                load_weight_lb=data["load_weight_lb"],
                interval_miles=data["interval_miles"],
                providers=get_providers(),
            )
        )


class HeatmapView(APIView):
    def post(self, request):
        ser = HeatmapRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        return Response(
            planner.heatmap_forecast(
                points=[(p["lat"], p["lon"]) for p in data["points"]],
                departure=data["departure"],
                load_weight_lb=data["load_weight_lb"],
                providers=get_providers(),
            )
        )
