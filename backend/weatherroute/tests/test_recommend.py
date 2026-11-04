from django.test import SimpleTestCase

from weatherroute.recommend import RouteMetrics, recommend


def m(rid, *, nt=0.0, sev=0.0, high=0.0, avg=0.0, hours=10.0):
    return RouteMetrics(rid, f"Route {rid}", nt, sev, high, avg, hours * 3600)


class RankingTests(SimpleTestCase):
    def best(self, *metrics):
        return recommend(list(metrics)).best_id

    def test_fewest_severe_miles_wins_over_everything_else(self):
        self.assertEqual(self.best(m("A", sev=40, high=0, avg=0.1, hours=8), m("B", sev=0, high=200, avg=0.9, hours=14)), "B")

    def test_then_fewest_high_miles(self):
        self.assertEqual(self.best(m("A", high=80, avg=0.2, hours=8), m("B", high=20, avg=0.3, hours=14)), "B")

    def test_then_lowest_average_risk(self):
        self.assertEqual(self.best(m("A", avg=0.50, hours=8), m("B", avg=0.30, hours=14)), "B")

    def test_then_shortest_time(self):
        self.assertEqual(self.best(m("A", avg=0.3, hours=9), m("B", avg=0.3, hours=8)), "B")

    def test_no_travel_beats_a_shorter_severe_count(self):
        # Route A has no Severe miles but one No Travel mile: it can't be driven, so B wins.
        self.assertEqual(self.best(m("A", nt=1, sev=0), m("B", nt=0, sev=60)), "B")

    def test_small_differences_are_ties_so_travel_time_can_decide(self):
        # 2 Severe miles vs 0 is inside the 5-mile tie band -> the faster route wins.
        self.assertEqual(self.best(m("A", sev=2, hours=8), m("B", sev=0, hours=12)), "A")
        # but 20 miles is a real difference
        self.assertEqual(self.best(m("A", sev=20, hours=8), m("B", sev=0, hours=12)), "B")

    def test_identical_routes_break_ties_by_id(self):
        self.assertEqual(self.best(m("B"), m("A")), "A")

    def test_ranking_lists_all_routes_best_first(self):
        rec = recommend([m("A", sev=30), m("B", sev=0), m("C", sev=10)])
        self.assertEqual(rec.ranking, ["B", "C", "A"])


class ExplanationTests(SimpleTestCase):
    def test_reasons_name_the_deciding_criterion(self):
        rec = recommend([m("A", sev=40, hours=8), m("B", sev=0, hours=10)])
        self.assertTrue(any("Beats Route A on Severe miles: 0.0 mi vs 40 mi" in r for r in rec.reasons))
        self.assertTrue(any("120 min longer than Route A" in r for r in rec.reasons))

    def test_no_slower_note_when_best_is_fastest(self):
        rec = recommend([m("A", hours=8), m("B", high=50, hours=9)])
        self.assertFalse(any("longer than" in r for r in rec.reasons))

    def test_summary_variants(self):
        self.assertIn("clear of High and Severe", recommend([m("A")]).summary)
        self.assertIn("avoids Severe", recommend([m("A", high=30)]).summary)
        self.assertIn("still has", recommend([m("A", sev=30)]).summary)

    def test_blocked_when_every_route_crosses_no_travel(self):
        rec = recommend([m("A", nt=20), m("B", nt=5)])
        self.assertTrue(rec.blocked)
        self.assertEqual(rec.best_id, "B")
        self.assertIn("different time", rec.summary)
