from django.test import SimpleTestCase

from weatherroute.risk import RAIN, SNOW, WIND, Risk, assess, classify, describe, rules_payload

L, M, H, S, N = Risk.LOW, Risk.MODERATE, Risk.HIGH, Risk.SEVERE, Risk.NO_TRAVEL


class ClassifyTests(SimpleTestCase):
    def check(self, scale, cases):
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(classify(value, scale), expected)

    def test_wind_bands(self):
        self.check(WIND, [
            (0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H),
            (45, S), (54.9, S), (55, N), (80, N),
        ])

    def test_rain_bands(self):
        self.check(RAIN, [
            (0, L), (0.09, L), (0.10, M), (0.24, M), (0.25, H), (0.49, H),
            (0.50, S), (1.00, S), (1.001, N), (3.0, N),
        ])

    def test_snow_bands(self):
        self.check(SNOW, [
            (0, L), (0.4, L), (0.5, M), (0.9, M), (1.0, H), (1.9, H),
            (2.0, S), (3.0, S), (3.01, N),
        ])

    def test_float_noise_does_not_cross_a_boundary(self):
        self.assertEqual(classify(0.24999999, RAIN), H)  # rounds to 0.25 -> High, by convention
        self.assertEqual(classify(1.0000001, RAIN), S)  # rounds to 1.0 -> still Severe


class AssessTests(SimpleTestCase):
    def test_overall_level_is_worst_condition(self):
        a = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=0.6, load_weight_lb=20_000)
        self.assertEqual((a.wind, a.rain, a.snow, a.level), (L, H, M, H))
        self.assertEqual(a.drivers, ("rain",))

    def test_low_has_no_drivers(self):
        a = assess(5, 0, 0, 80_000)
        self.assertEqual((a.level, a.drivers), (L, ()))
        self.assertEqual(describe(a, 5, 0, 0), "No significant weather.")

    def test_wind_55_is_no_travel_for_any_load(self):
        for load in (0, 10_000, 80_000):
            with self.subTest(load=load):
                self.assertEqual(assess(55, 0, 0, load).level, N)

    def test_wind_45_to_54_no_travel_only_above_30k(self):
        self.assertEqual(assess(50, 0, 0, 30_000).level, S)  # not strictly greater
        self.assertEqual(assess(50, 0, 0, 30_001).level, N)
        self.assertEqual(assess(45, 0, 0, 35_000).level, N)
        self.assertEqual(assess(54.9, 0, 0, 35_000).level, N)
        self.assertEqual(assess(50, 0, 0, 10_000).level, S)

    def test_wind_35_to_44_severe_only_above_40k(self):
        self.assertEqual(assess(40, 0, 0, 40_000).level, H)  # not strictly greater
        self.assertEqual(assess(40, 0, 0, 40_001).level, S)
        self.assertEqual(assess(35, 0, 0, 50_000).level, S)
        self.assertEqual(assess(44.9, 0, 0, 50_000).level, S)
        self.assertEqual(assess(40, 0, 0, 20_000).level, H)

    def test_load_rule_only_applies_to_wind(self):
        self.assertEqual(assess(10, 0.3, 0, 80_000).level, H)  # heavy load, calm wind, rain: High

    def test_load_rule_never_lowers_a_worse_level(self):
        self.assertEqual(assess(40, 0.6, 0, 50_000).level, S)  # rain Severe, wind->Severe
        self.assertEqual(assess(40, 1.2, 0, 50_000).level, N)  # rain No Travel wins

    def test_load_rule_is_reported(self):
        a = assess(40, 0, 0, 45_000)
        self.assertIn("load rule", a.load_rule)
        self.assertEqual(a.drivers, ("wind",))
        self.assertIn("load rule applied", describe(a, 40, 0, 0))
        self.assertIsNone(assess(40, 0, 0, 10_000).load_rule)

    def test_ties_list_every_driver(self):
        a = assess(40, 0.3, 0, 10_000)  # wind High, rain High
        self.assertEqual(a.drivers, ("wind", "rain"))


class RulesPayloadTests(SimpleTestCase):
    def test_payload_mirrors_thresholds(self):
        p = rules_payload()
        self.assertEqual(p["thresholds"]["wind"]["no_travel_over"], 55)
        self.assertEqual([lv["label"] for lv in p["levels"]], ["Low", "Moderate", "High", "Severe", "No Travel"])
        self.assertEqual(len(p["load_rules"]), 3)
