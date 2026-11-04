"""Request validation."""
from __future__ import annotations

from rest_framework import serializers

MAX_LOAD_LB = 100_000
MAX_HEATMAP_POINTS = 300


class LocationField(serializers.Field):
    """Either free text ("Denver, CO" / "39.74,-104.99") or {lat, lon, label?} from autocomplete."""

    default_error_messages = {
        "invalid": "Provide a place name or an object with lat and lon.",
        "blank": "This field may not be blank.",
        "range": "Coordinates are out of range.",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                self.fail("blank")
            return {"text": text[:200]}
        if isinstance(data, dict):
            try:
                lat, lon = float(data["lat"]), float(data["lon"])
            except (KeyError, TypeError, ValueError):
                self.fail("invalid")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                self.fail("range")
            label = data.get("label")
            return {"lat": lat, "lon": lon, "label": str(label)[:200] if label else None}
        self.fail("invalid")

    def to_representation(self, value):
        return value


class IntervalField(serializers.Field):
    default_error_messages = {"invalid": 'Must be "auto", 10, 25 or 50.'}

    def to_internal_value(self, data):
        if data in ("auto", None, ""):
            return "auto"
        try:
            value = int(data)
        except (TypeError, ValueError):
            self.fail("invalid")
        if value not in (10, 25, 50):
            self.fail("invalid")
        return value

    def to_representation(self, value):
        return value


class PlanRequestSerializer(serializers.Serializer):
    origin = LocationField()
    destination = LocationField()
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = IntervalField(required=False, default="auto")


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class HeatmapRequestSerializer(serializers.Serializer):
    points = PointSerializer(many=True, allow_empty=False, max_length=MAX_HEATMAP_POINTS)
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
