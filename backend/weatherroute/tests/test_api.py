from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APISimpleTestCase

from weatherroute.errors import UpstreamError
from weatherroute.providers.fake import build_fake_providers

PATCH = "weatherroute.views.get_providers"


def departure(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class ApiTests(APISimpleTestCase):
    def setUp(self):
        cache.clear()  # reset throttling
        patcher = mock.patch(PATCH, return_value=build_fake_providers())
        self.providers_patch = patcher.start()
        self.addCleanup(patcher.stop)

    def post_plan(self, **overrides):
        body = {"origin": "Chicago", "destination": "Denver", "departure": departure(), "load_weight_lb": 40000}
        body.update(overrides)
        return self.client.post("/api/plan", body, format="json")

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_risk_rules(self):
        data = self.client.get("/api/risk-rules").json()
        self.assertEqual(data["thresholds"]["rain"]["severe_from"], 0.5)

    def test_geocode_suggestions(self):
        data = self.client.get("/api/geocode", {"q": "den"}).json()
        self.assertEqual(data["results"][0]["label"], "Denver")
        self.assertEqual(self.client.get("/api/geocode", {"q": "de"}).status_code, 400)

    def test_plan_response_shape(self):
        resp = self.post_plan()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual(data["request"]["origin"]["label"], "Chicago")
        route = data["routes"][0]
        for key in ("id", "name", "distance_miles", "duration_s", "arrival", "summary", "segments", "checkpoints", "bounds"):
            self.assertIn(key, route)
        cp = route["checkpoints"][0]
        for key in ("mile", "eta", "level", "level_label", "wind_mph", "rain_in_hr", "snow_in_hr", "note"):
            self.assertIn(key, cp)
        self.assertIn(data["recommended_route_id"], [r["id"] for r in data["routes"]])

    def test_plan_accepts_coordinates_from_autocomplete_and_explicit_interval(self):
        resp = self.post_plan(
            origin={"lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL"},
            destination={"lat": 39.7392, "lon": -104.9903},
            interval_miles=25,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["request"]["origin"]["label"], "Chicago, IL")
        self.assertEqual({r["checkpoint_interval_miles"] for r in data["routes"]}, {25})

    def test_validation_errors_have_a_consistent_shape(self):
        resp = self.post_plan(load_weight_lb=-1, origin="")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["code"], "validation_error")
        self.assertIn("load_weight_lb", body["fields"])
        self.assertIn("origin", body["fields"])

    def test_bad_interval_is_rejected(self):
        self.assertEqual(self.post_plan(interval_miles=17).status_code, 400)

    def test_unknown_place_is_422(self):
        resp = self.post_plan(origin="Atlantis")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["code"], "location_not_found")

    def test_past_departure_is_400(self):
        resp = self.post_plan(departure=departure(-30))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "invalid_request")

    def test_upstream_failure_is_502_with_message(self):
        providers = build_fake_providers()
        providers.weather = mock.Mock(series_for=mock.Mock(side_effect=UpstreamError("Weather service is unavailable right now.")))
        with mock.patch(PATCH, return_value=providers):
            resp = self.post_plan()
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Weather service", resp.json()["detail"])

    def test_heatmap_roundtrip(self):
        plan = self.post_plan().json()
        dep = plan["request"]["departure"]
        resp = self.client.post(
            "/api/heatmap",
            {"points": plan["heatmap"]["points"][:20], "departure": dep, "load_weight_lb": 40000},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data["points"]), 20)
        self.assertEqual(len(data["points"][0]["risk"]), 49)

    def test_heatmap_validation(self):
        resp = self.client.post("/api/heatmap", {"points": [], "departure": departure(), "load_weight_lb": 1}, format="json")
        self.assertEqual(resp.status_code, 400)
        too_many = [{"lat": 40, "lon": -100}] * 301
        resp = self.client.post("/api/heatmap", {"points": too_many, "departure": departure(), "load_weight_lb": 1}, format="json")
        self.assertEqual(resp.status_code, 400)
