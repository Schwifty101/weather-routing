"""Provider parsing / fallback logic against canned upstream responses (no network)."""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from weatherroute.domain import Location
from weatherroute.errors import LocationNotFound, UpstreamError
from weatherroute.providers.geocode import Geocoder, NominatimGeocoder, PhotonGeocoder, parse_latlon
from weatherroute.providers.openmeteo import OpenMeteoProvider
from weatherroute.providers.osrm import OSRMRouter


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class FakeSession:
    """Routes each GET to `handler(url, params) -> FakeResponse` and records calls."""

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.handler(url, params)


def osrm_route(coords_lonlat, miles, hours):
    meters, seconds = miles * 1609.344, hours * 3600
    half = len(coords_lonlat) // 2
    return {
        "geometry": {"coordinates": coords_lonlat},
        "distance": meters,
        "duration": seconds,
        "legs": [{"steps": [
            {"distance": meters * 0.25, "duration": seconds * 0.5},  # slow first quarter
            {"distance": meters * 0.75, "duration": seconds * 0.5},
        ]}],
        "_half": half,
    }


def straight(lat, n=40, lon0=-100.0, dlon=0.05):
    return [[lon0 + i * dlon, lat] for i in range(n)]


ORIGIN = Location("A", 40.0, -100.0)
DEST = Location("B", 40.0, -98.05)


class OSRMTests(SimpleTestCase):
    def router(self, handler):
        return OSRMRouter("https://osrm.test", FakeSession(handler))

    def test_parses_geometry_distance_duration_and_step_profile(self):
        body = {"code": "Ok", "routes": [osrm_route(straight(40.0), 135, 2.0)]}
        routes = self.router(lambda u, p: FakeResponse(body)).get_route_options(ORIGIN, DEST)
        r = routes[0]
        self.assertEqual(r.coords[0], (40.0, -100.0))  # lon/lat flipped to lat/lon
        self.assertAlmostEqual(r.distance_mi, 135, places=3)
        self.assertEqual(r.duration_s, 7200)
        self.assertEqual(r.profile[0], (0.0, 0.0))
        self.assertAlmostEqual(r.profile[1][0], 0.25)
        self.assertAlmostEqual(r.profile[1][1], 3600)  # first quarter of the road took half the time

    def test_returns_three_distinct_alternatives_directly(self):
        body = {"code": "Ok", "routes": [
            osrm_route(straight(40.0), 135, 2.0),
            osrm_route(straight(41.0), 140, 2.1),
            osrm_route(straight(42.0), 150, 2.4),
        ]}
        sess_router = self.router(lambda u, p: FakeResponse(body))
        routes = sess_router.get_route_options(ORIGIN, DEST)
        self.assertEqual(len(routes), 3)
        self.assertEqual(len(sess_router.session.calls), 1)  # no via-point fallback needed
        self.assertEqual([r.duration_s for r in routes], sorted(r.duration_s for r in routes))

    def test_near_duplicate_alternatives_are_dropped(self):
        body = {"code": "Ok", "routes": [osrm_route(straight(40.0), 135, 2.0), osrm_route(straight(40.002), 135, 2.0)]}
        routes = self.router(lambda u, p: FakeResponse(body)).get_route_options(ORIGIN, DEST, want=1)
        self.assertEqual(len(routes), 1)

    def test_via_waypoint_fallback_when_osrm_offers_no_alternatives(self):
        def handler(url, params):
            n_waypoints = url.rsplit("/", 1)[1].count(";") + 1
            if n_waypoints == 2:
                return FakeResponse({"code": "Ok", "routes": [osrm_route(straight(40.0), 135, 2.0)]})
            # via request: return a route that bows north, further for later attempts
            lat = 40.0 + 0.3 * len(self_.session.calls)
            return FakeResponse({"code": "Ok", "routes": [osrm_route(straight(lat), 150, 2.3)]})

        self_ = self.router(handler)
        routes = self_.get_route_options(ORIGIN, DEST)
        self.assertEqual(len(routes), 3)
        urls = [c[0] for c in self_.session.calls]
        self.assertTrue(any(u.rsplit("/", 1)[1].count(";") == 2 for u in urls))  # used a via point

    def test_crazy_detours_are_rejected(self):
        def handler(url, params):
            if url.rsplit("/", 1)[1].count(";") == 1:
                return FakeResponse({"code": "Ok", "routes": [osrm_route(straight(40.0), 135, 2.0)]})
            return FakeResponse({"code": "Ok", "routes": [osrm_route(straight(44.0), 400, 6.0)]})

        routes = self.router(handler).get_route_options(ORIGIN, DEST)
        self.assertEqual(len(routes), 1)

    def test_no_route_returns_empty(self):
        routes = self.router(lambda u, p: FakeResponse({"code": "NoRoute"}, 400)).get_route_options(ORIGIN, DEST)
        self.assertEqual(routes, [])

    def test_falls_back_to_boolean_alternatives_for_old_servers(self):
        seen = []

        def handler(url, params):
            seen.append(params["alternatives"])
            if params["alternatives"] == "3":
                return FakeResponse({"code": "InvalidQuery", "message": "bad alternatives"}, 400)
            return FakeResponse({"code": "Ok", "routes": [osrm_route(straight(40.0), 135, 2.0)]})

        self.router(handler).get_route_options(ORIGIN, DEST, want=1)
        self.assertEqual(seen[:2], ["3", "true"])

    def test_server_error_code_raises(self):
        with self.assertRaises(UpstreamError):
            self.router(lambda u, p: FakeResponse({"code": "TooBig", "message": "nope"}, 400)).get_route_options(ORIGIN, DEST)


def meteo_item(times, wind, gust, rain, showers, snow):
    return {"hourly": {"time": times, "wind_speed_10m": wind, "wind_gusts_10m": gust,
                       "rain": rain, "showers": showers, "snowfall": snow}}


TIMES = ["2026-11-04T00:00", "2026-11-04T01:00", "2026-11-04T02:00"]


class OpenMeteoTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def provider(self, handler):
        return OpenMeteoProvider("https://meteo.test/v1/forecast", FakeSession(handler))

    def test_parses_multi_location_response_and_sums_rain_and_showers(self):
        items = [
            meteo_item(TIMES, [10, 20, 30], [15, 25, 35], [0.1, 0.0, None], [0.05, 0.0, 0.2], [0, 0.5, 0]),
            meteo_item(TIMES, [1, 2, 3], [2, 3, 4], [0, 0, 0], [0, 0, 0], [0, 0, 0]),
        ]
        prov = self.provider(lambda u, p: FakeResponse(items))
        a, b = prov.series_for([(40.0, -100.0), (41.0, -99.0)])
        self.assertEqual(a.wind, [10, 20, 30])
        self.assertEqual(a.rain, [0.15000000000000002, 0.0, 0.2])  # None -> 0, rain + showers
        self.assertEqual(a.snow, [0, 0.5, 0])
        self.assertEqual(a.times[1] - a.times[0], 3600)
        self.assertEqual(a.times[0], 1793750400)  # 2026-11-04T00:00Z
        self.assertEqual(b.gust, [2, 3, 4])

    def test_requests_the_units_the_rules_use(self):
        prov = self.provider(lambda u, p: FakeResponse([meteo_item(TIMES, [1] * 3, [1] * 3, [0] * 3, [0] * 3, [0] * 3)]))
        prov.series_for([(40.0, -100.0)])
        params = prov.session.calls[0][1]
        self.assertEqual((params["wind_speed_unit"], params["precipitation_unit"], params["timezone"]),
                         ("mph", "inch", "GMT"))

    def test_single_location_dict_response(self):
        prov = self.provider(lambda u, p: FakeResponse(meteo_item(TIMES, [1] * 3, [1] * 3, [0] * 3, [0] * 3, [0] * 3)))
        self.assertEqual(len(prov.series_for([(40.0, -100.0)])), 1)

    def test_duplicates_are_fetched_once_and_cached_across_calls(self):
        def handler(url, params):
            n = len(params["latitude"].split(","))
            return FakeResponse([meteo_item(TIMES, [1] * 3, [1] * 3, [0] * 3, [0] * 3, [0] * 3)] * n)

        prov = self.provider(handler)
        out = prov.series_for([(40.001, -100.001), (40.002, -100.002), (41.0, -99.0)])
        self.assertEqual(len(out), 3)
        self.assertEqual(len(prov.session.calls[0][1]["latitude"].split(",")), 2)  # snapped to 2 unique points
        prov.series_for([(40.0, -100.0)])
        self.assertEqual(len(prov.session.calls), 1)  # served from cache

    def test_large_batches_are_chunked(self):
        def handler(url, params):
            n = len(params["latitude"].split(","))
            return FakeResponse([meteo_item(TIMES, [1] * 3, [1] * 3, [0] * 3, [0] * 3, [0] * 3)] * n)

        prov = self.provider(handler)
        points = [(30.0 + i * 0.1, -100.0) for i in range(200)]
        self.assertEqual(len(prov.series_for(points)), 200)
        self.assertEqual(len(prov.session.calls), 3)  # 80 + 80 + 40

    def test_api_error_body_raises(self):
        prov = self.provider(lambda u, p: FakeResponse({"error": True, "reason": "Latitude must be in range"}, 400))
        with self.assertRaisesMessage(UpstreamError, "Latitude must be in range"):
            prov.series_for([(95.0, 0.0)])

    def test_malformed_payload_raises(self):
        prov = self.provider(lambda u, p: FakeResponse([{"hourly": {"time": TIMES}}]))
        with self.assertRaises(UpstreamError):
            prov.series_for([(40.0, -100.0)])

    @mock.patch("weatherroute.providers.http.time.sleep")
    def test_transient_failures_are_retried(self, _sleep):
        responses = iter([FakeResponse({}, 503), FakeResponse([meteo_item(TIMES, [1] * 3, [1] * 3, [0] * 3, [0] * 3, [0] * 3)])])
        prov = self.provider(lambda u, p: next(responses))
        self.assertEqual(len(prov.series_for([(40.0, -100.0)])), 1)

    @mock.patch("weatherroute.providers.http.time.sleep")
    def test_persistent_failure_raises_upstream_error(self, _sleep):
        prov = self.provider(lambda u, p: FakeResponse({}, 503))
        with self.assertRaises(UpstreamError):
            prov.series_for([(40.0, -100.0)])
        self.assertEqual(len(prov.session.calls), 3)


class GeocodeTests(SimpleTestCase):
    PHOTON = {"features": [
        {"geometry": {"coordinates": [-104.99, 39.74]}, "properties": {"name": "Denver", "state": "Colorado", "country": "United States"}},
        {"geometry": {"coordinates": [-105.0, 39.7]}, "properties": {"name": "Denver", "city": "Denver", "state": "Colorado"}},
    ]}

    def test_parse_latlon(self):
        self.assertEqual((parse_latlon("39.74, -104.99").lat, parse_latlon("39.74 -104.99").lon), (39.74, -104.99))
        self.assertIsNone(parse_latlon("Denver, CO"))

    def test_photon_label_and_coordinates(self):
        g = PhotonGeocoder("https://photon.test", FakeSession(lambda u, p: FakeResponse(self.PHOTON)))
        first, second = g.search("Denver")
        self.assertEqual((first.label, first.lat, first.lon), ("Denver, Colorado, United States", 39.74, -104.99))
        self.assertEqual(second.label, "Denver, Colorado")  # consecutive duplicates collapsed

    def test_nominatim_parse(self):
        data = [{"display_name": "Denver, Colorado, USA", "lat": "39.7392", "lon": "-104.9903"}]
        g = NominatimGeocoder("https://nom.test", FakeSession(lambda u, p: FakeResponse(data)))
        self.assertEqual(g.search("Denver")[0].lat, 39.7392)

    @mock.patch("weatherroute.providers.http.time.sleep")
    def test_falls_back_to_second_backend_when_first_is_down(self, _sleep):
        down = PhotonGeocoder("https://photon.test", FakeSession(lambda u, p: FakeResponse({}, 503)))
        up = NominatimGeocoder("https://nom.test", FakeSession(
            lambda u, p: FakeResponse([{"display_name": "Denver", "lat": "39.7", "lon": "-105.0"}])))
        self.assertEqual(Geocoder([down, up]).resolve("Denver").label, "Denver")

    def test_empty_result_does_not_trigger_fallback_and_raises_not_found(self):
        empty = PhotonGeocoder("https://photon.test", FakeSession(lambda u, p: FakeResponse({"features": []})))
        other = mock.Mock()
        with self.assertRaises(LocationNotFound):
            Geocoder([empty, other]).resolve("Nowhereville")
        other.search.assert_not_called()

    def test_literal_coordinates_skip_the_network(self):
        backend = mock.Mock()
        self.assertEqual(Geocoder([backend]).resolve("39.7392,-104.9903").lat, 39.7392)
        backend.search.assert_not_called()
