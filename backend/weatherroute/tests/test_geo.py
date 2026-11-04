import math

from django.test import SimpleTestCase

from weatherroute import geo


def line(n=11, lat0=40.0, lon0=-100.0, dlon=0.1):
    return [(lat0, lon0 + i * dlon) for i in range(n)]


class DistanceTests(SimpleTestCase):
    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(geo.haversine_mi((40, -100), (41, -100)), 69.09, delta=0.1)

    def test_cumulative_is_monotonic_and_starts_at_zero(self):
        cum = geo.cumulative_miles(line())
        self.assertEqual(cum[0], 0.0)
        self.assertTrue(all(b > a for a, b in zip(cum, cum[1:])))

    def test_point_at_interpolates_and_clamps(self):
        pts = line()
        cum = geo.cumulative_miles(pts)
        mid = geo.point_at(pts, cum, cum[-1] / 2)
        self.assertAlmostEqual(mid[1], -99.5, places=3)
        self.assertEqual(geo.point_at(pts, cum, -5), pts[0])
        self.assertEqual(geo.point_at(pts, cum, 1e9), pts[-1])


class SampleDistanceTests(SimpleTestCase):
    def test_exact_multiple(self):
        self.assertEqual(geo.sample_distances(100, 25), [0, 25, 50, 75, 100])

    def test_remainder_gets_its_own_final_checkpoint(self):
        self.assertEqual(geo.sample_distances(110, 25), [0, 25, 50, 75, 100, 110])

    def test_near_duplicate_final_interior_point_is_dropped(self):
        self.assertEqual(geo.sample_distances(101, 25), [0, 25, 50, 75, 101])

    def test_short_route(self):
        self.assertEqual(geo.sample_distances(6, 25), [0, 6])
        self.assertEqual(geo.sample_distances(0, 25), [0.0])


class SliceTests(SimpleTestCase):
    def test_slice_has_exact_end_points_and_inner_vertices(self):
        pts = line()
        cum = geo.cumulative_miles(pts)
        a, b = cum[2] + 0.1, cum[5] - 0.1
        part = geo.slice_polyline(pts, cum, a, b)
        self.assertEqual(part[1:-1], pts[3:5])
        self.assertAlmostEqual(geo.cumulative_miles(part)[-1], b - a, places=4)

    def test_adjacent_slices_tile_the_route(self):
        pts = line()
        cum = geo.cumulative_miles(pts)
        cuts = [0, cum[-1] / 3, 2 * cum[-1] / 3, cum[-1]]
        total = sum(geo.cumulative_miles(geo.slice_polyline(pts, cum, a, b))[-1] for a, b in zip(cuts, cuts[1:]))
        self.assertAlmostEqual(total, cum[-1], places=4)


class SimplifyTests(SimpleTestCase):
    def test_straight_line_collapses_to_endpoints(self):
        pts = line(50)
        self.assertEqual(geo.simplify(pts, 0.01), [pts[0], pts[-1]])

    def test_corner_is_kept(self):
        pts = [(40, -100), (40, -99.5), (40, -99), (40.5, -99), (41, -99)]
        out = geo.simplify(pts, 0.05)
        self.assertIn((40, -99), out)
        self.assertEqual((out[0], out[-1]), (pts[0], pts[-1]))


class DestinationTests(SimpleTestCase):
    def test_destination_point_round_trips_distance_and_bearing(self):
        start = (40.0, -100.0)
        end = geo.destination_point(start, 90, 50)
        self.assertAlmostEqual(geo.haversine_mi(start, end), 50, places=3)
        self.assertAlmostEqual(geo.bearing_deg(start, end), 90, delta=0.5)


class OverlapTests(SimpleTestCase):
    def test_identical_routes_share_everything(self):
        self.assertAlmostEqual(geo.shared_fraction(line(), line()), 1.0)

    def test_parallel_routes_far_apart_share_nothing(self):
        far = [(p[0] + 0.5, p[1]) for p in line()]  # ~35 miles north
        self.assertAlmostEqual(geo.shared_fraction(line(), far), 0.0)

    def test_partial_overlap(self):
        a = line(21)  # 0.0 .. 2.0 degrees east
        b = line(11) + [(40.5 + i * 0.05, -99.0 + i * 0.1) for i in range(1, 11)]  # shares first half
        frac = geo.shared_fraction(a, b)
        self.assertGreater(frac, 0.3)
        self.assertLess(frac, 0.8)


class CorridorTests(SimpleTestCase):
    def test_respects_point_budget_and_covers_corridor(self):
        a = [(41.0 - i * 0.02, -88.0 - i * 0.2) for i in range(1000)]
        b = [(p[0] + 0.5 * math.sin(i / 160), p[1]) for i, p in enumerate(a)]
        pts, spacing = geo.corridor_points([a, b], max_points=120)
        self.assertLessEqual(len(pts), 120)
        self.assertGreater(spacing, 15)
        lats = [p[0] for p in pts]
        self.assertLess(min(lats), min(p[0] for p in a))  # lateral offsets widen the corridor
        self.assertEqual(len(pts), len(set(pts)))
