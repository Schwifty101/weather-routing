from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase, override_settings

from weatherroute import geo, planner
from weatherroute.domain import Providers
from weatherroute.errors import ForecastUnavailable, InvalidRequest
from weatherroute.providers.fake import FakeGeocoder, FakeRouter, FakeWeather

START = datetime(2026, 11, 4, tzinfo=timezone.utc).timestamp()  # forecast series start
NOW = START + 3600
DEPARTURE = datetime.fromtimestamp(START + 2 * 3600, tz=timezone.utc)

CALM = (5.0, 7.0, 0.0, 0.0)


def providers(field=None, hours=7 * 24):
    return Providers(FakeGeocoder(), FakeRouter(), FakeWeather(field or (lambda lat, lon, t: CALM), START, hours))


def plan(prov, *, load=42_000, interval="auto", departure=DEPARTURE, origin="Chicago", dest="Denver"):
    return planner.plan_trip(
        origin={"text": origin}, destination={"text": dest}, departure=departure,
        load_weight_lb=load, interval_miles=interval, providers=prov, now=NOW,
    )


class IntervalTests(SimpleTestCase):
    def test_auto_scales_with_trip_length(self):
        self.assertEqual(planner.choose_interval("auto", 80), 10)
        self.assertEqual(planner.choose_interval("auto", 400), 25)
        self.assertEqual(planner.choose_interval("auto", 1800), 50)

    def test_explicit_choice_is_respected(self):
        for n in (10, 25, 50):
            self.assertEqual(planner.choose_interval(n, 1800), n)


class CalmWeatherTests(SimpleTestCase):
    def setUp(self):
        self.prov = providers()
        self.result = plan(self.prov)

    def test_three_routes_all_low_risk(self):
        self.assertEqual(len(self.result["routes"]), 3)
        for route in self.result["routes"]:
            self.assertEqual(route["summary"]["max_level"], 0)
            self.assertEqual(route["summary"]["avg_risk"], 0)

    def test_fastest_route_is_recommended_when_weather_is_equal(self):
        self.assertEqual(self.result["recommended_route_id"], "route-1")
        best = self.result["routes"][0]
        self.assertTrue(best["recommended"] and best["fastest"] and best["rank"] == 1)
        self.assertFalse(self.result["recommendation"]["blocked"])

    def test_weather_is_fetched_in_one_batch(self):
        self.assertEqual(len(self.prov.weather.calls), 1)

    def test_level_miles_tile_the_route(self):
        for route in self.result["routes"]:
            total = sum(route["summary"]["miles_by_level"].values())
            self.assertAlmostEqual(total, route["distance_miles"], delta=0.3)

    def test_checkpoints_start_at_origin_end_at_destination_and_ascend(self):
        for route in self.result["routes"]:
            cps = route["checkpoints"]
            self.assertEqual(cps[0]["mile"], 0)
            self.assertAlmostEqual(cps[-1]["mile"], route["distance_miles"], delta=0.1)
            self.assertEqual([c["mile"] for c in cps], sorted(c["mile"] for c in cps))
            etas = [c["eta"] for c in cps]
            self.assertEqual(etas, sorted(etas))

    def test_segments_cover_the_whole_route(self):
        for route in self.result["routes"]:
            segs = route["segments"]
            self.assertEqual(segs[0]["from_mile"], 0)
            self.assertAlmostEqual(segs[-1]["to_mile"], route["distance_miles"], delta=0.1)
            for a, b in zip(segs, segs[1:]):
                self.assertEqual(a["to_mile"], b["from_mile"])

    def test_heatmap_points_are_returned_for_a_second_request(self):
        heat = self.result["heatmap"]
        self.assertEqual(heat["hours"], 49)
        self.assertTrue(0 < len(heat["points"]) <= 180)


class EtaTests(SimpleTestCase):
    @override_settings(TRUCK_DURATION_FACTOR=1.0)
    def test_arrival_equals_departure_plus_route_duration(self):
        result = plan(providers())
        for route in result["routes"]:
            dep = datetime.fromisoformat(result["request"]["departure"].replace("Z", "+00:00"))
            arr = datetime.fromisoformat(route["arrival"].replace("Z", "+00:00"))
            self.assertAlmostEqual((arr - dep).total_seconds(), route["duration_s"], delta=1)

    @override_settings(TRUCK_DURATION_FACTOR=1.25)
    def test_truck_factor_scales_durations(self):
        slow = plan(providers())["routes"][0]["duration_s"]
        with override_settings(TRUCK_DURATION_FACTOR=1.0):
            fast = plan(providers())["routes"][0]["duration_s"]
        self.assertAlmostEqual(slow / fast, 1.25, places=2)

    def test_interval_changes_checkpoint_count(self):
        counts = {n: len(plan(providers(), interval=n)["routes"][0]["checkpoints"]) for n in (10, 25, 50)}
        self.assertGreater(counts[10], counts[25])
        self.assertGreater(counts[25], counts[50])

    def test_checkpoint_weather_uses_eta_not_departure(self):
        # Wind arrives 6h after the start of the forecast everywhere; only later checkpoints see it.
        gale_from = START + 8 * 3600

        def field(lat, lon, t):
            return (60.0, 70.0, 0, 0) if t >= gale_from else CALM

        route = plan(providers(field), interval=50)["routes"][0]
        levels = [c["level"] for c in route["checkpoints"]]
        self.assertEqual(levels[0], 0)
        self.assertEqual(levels[-1], 4)
        self.assertEqual(levels, sorted(levels))  # once the gale starts it never stops


class WeatherDifferencesTests(SimpleTestCase):
    """Wind only on the northern bulge (Route B) must steer the recommendation away from it."""

    def setUp(self):
        coords = {
            r.duration_s: r.coords
            for r in FakeRouter().get_route_options(
                FakeGeocoder().resolve("Chicago"), FakeGeocoder().resolve("Denver")
            )
        }
        a, b = (max(p[0] for p in c) for c in list(coords.values())[:2])
        self.cutoff = (a + b) / 2  # between the direct route's and B's northernmost point

    def field(self, wind):
        return lambda lat, lon, t: (wind, wind * 1.2, 0.0, 0.0) if lat > self.cutoff else CALM

    def test_recommendation_avoids_the_stormy_route(self):
        result = plan(providers(self.field(50.0)), load=25_000)  # 50 mph, light load -> Severe
        by_id = {r["id"]: r for r in result["routes"]}
        self.assertGreater(by_id["route-2"]["summary"]["miles_by_level"]["severe"], 0)
        self.assertEqual(by_id["route-1"]["summary"]["miles_by_level"]["severe"], 0)
        self.assertEqual(result["recommended_route_id"], "route-1")
        self.assertEqual(by_id["route-2"]["rank"], 3)

    def test_load_weight_changes_the_outcome(self):
        light = plan(providers(self.field(50.0)), load=25_000)
        heavy = plan(providers(self.field(50.0)), load=42_000)  # >30k at 45-54 mph -> No Travel
        light_b = next(r for r in light["routes"] if r["id"] == "route-2")["summary"]["miles_by_level"]
        heavy_b = next(r for r in heavy["routes"] if r["id"] == "route-2")["summary"]["miles_by_level"]
        self.assertEqual(light_b["no_travel"], 0)
        self.assertGreater(heavy_b["no_travel"], 0)
        self.assertEqual(heavy["recommended_route_id"], "route-1")

    def test_all_routes_blocked_is_reported(self):
        result = plan(providers(lambda lat, lon, t: (60.0, 70.0, 0, 0)))
        self.assertTrue(result["recommendation"]["blocked"])
        self.assertTrue(all(r["summary"]["max_level"] == 4 for r in result["routes"]))

    @override_settings(WIND_METRIC="gust")
    def test_gust_metric_switch(self):
        # sustained 20 mph is Low, gusts of 60 mph are No Travel
        result = plan(providers(lambda lat, lon, t: (20.0, 60.0, 0, 0)))
        self.assertTrue(result["recommendation"]["blocked"])


class ForecastHorizonTests(SimpleTestCase):
    def test_arrival_beyond_forecast_is_flagged(self):
        result = plan(providers(hours=10))  # forecast ends 10h after START, trip takes ~17h
        self.assertTrue(result["warnings"])
        self.assertTrue(any(c["forecast_clamped"] for r in result["routes"] for c in r["checkpoints"]))

    def test_departure_in_the_past_is_rejected(self):
        with self.assertRaises(InvalidRequest):
            plan(providers(), departure=datetime.fromtimestamp(NOW - 5 * 3600, tz=timezone.utc))

    def test_departure_beyond_horizon_is_rejected(self):
        with self.assertRaises(ForecastUnavailable):
            plan(providers(), departure=datetime.fromtimestamp(NOW + 9 * 86400, tz=timezone.utc))

    def test_same_origin_and_destination_is_rejected(self):
        with self.assertRaises(InvalidRequest):
            plan(providers(), origin="Denver", dest="39.74,-104.99")


class HeatmapTests(SimpleTestCase):
    def points(self):
        return [(41.0, -95.0), (40.0, -100.0)]

    def test_hourly_offsets_start_at_departure(self):
        gale_from = START + 11 * 3600  # departure is START+2h, so offset 9h

        def field(lat, lon, t):
            return (60.0, 70.0, 0, 0) if t >= gale_from else CALM

        out = planner.heatmap_forecast(
            points=self.points(), departure=DEPARTURE, load_weight_lb=20_000, providers=providers(field), now=NOW
        )
        risk = out["points"][0]["risk"]
        self.assertEqual(len(risk), 49)
        self.assertEqual(risk[8], 0)
        self.assertEqual(risk[9], 4)
        self.assertEqual(out["points"][0]["wind"][9], 60)

    def test_load_rules_apply_to_the_heatmap(self):
        prov = providers(lambda lat, lon, t: (40.0, 48.0, 0, 0))
        heavy = planner.heatmap_forecast(points=self.points(), departure=DEPARTURE, load_weight_lb=45_000, providers=prov, now=NOW)
        light = planner.heatmap_forecast(points=self.points(), departure=DEPARTURE, load_weight_lb=20_000, providers=prov, now=NOW)
        self.assertEqual(heavy["points"][0]["risk"][0], 3)  # Severe via load rule
        self.assertEqual(light["points"][0]["risk"][0], 2)  # High

    def test_reports_how_many_forecast_hours_exist(self):
        out = planner.heatmap_forecast(
            points=self.points(), departure=DEPARTURE, load_weight_lb=0, providers=providers(hours=20), now=NOW
        )
        self.assertEqual(out["forecast_hours_available"], 17)  # 19h of data after START+... minus 2h offset
