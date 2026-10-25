"""Tests for the mart loader and the "Compared with other cars like this" section."""

import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

import duckdb
from django.core.management import call_command
from django.test import TestCase, override_settings

from .analysis import build_report
from .comparison import build_comparison, mileage_comparison
from .models import ModelYearDefectCategory, ModelYearFailRate, OdometerRounding
from .sample_data import load_sample


def make_rate(**overrides):
    values = dict(model_year_key="k-2016", make="FORD", model="FIESTA", make_slug="ford",
                  model_slug="fiesta", first_use_year=2016,
                  test_year=2024, tests=114221, initial_fails=35728, initial_fail_rate_pct=31.28,
                  final_fail_rate_pct=25.0, initial_fail_rate_low_pct=31.01,
                  initial_fail_rate_high_pct=31.55, estimated_initial_fail_rate_pct=31.27,
                  estimated_low_pct=31.0, estimated_high_pct=31.54,
                  median_mileage=60000, mileage_readings=100000, miles_per_year_p10=3500,
                  miles_per_year_p25=5200, miles_per_year_p50=7000, miles_per_year_p75=9100,
                  miles_per_year_p90=11800, peer_tests=2_000_000, peer_initial_fail_rate_pct=23.33,
                  peer_final_fail_rate_pct=19.0, initial_fail_rate_vs_peers_pts=7.95,
                  peer_between_model_sd_pts=3.0, funnel_low_95_pct=17.4, funnel_high_95_pct=29.2,
                  funnel_low_998_pct=14.0, funnel_high_998_pct=32.6, vs_peers="higher",
                  funnel_position="above")
    values.update(overrides)
    return ModelYearFailRate.objects.create(**values)


def add_category(rate, name, share, peer, low=None):
    return ModelYearDefectCategory.objects.create(
        model_year=rate, defect_category=name, tests_with_failure_item=1,
        tests_with_advisory=1, failure_share_pct=share,
        failure_share_low_pct=share - 0.3 if low is None else low, advisory_share_pct=1.0,
        peer_failure_share_pct=peer, peer_advisory_share_pct=1.0)


FIESTA_2016 = {"make": "FORD", "model": "FIESTA", "first_used": datetime(2016, 1, 1)}


class LoaderTests(TestCase):
    def make_warehouse(self, folder):
        path = Path(folder) / "mot.duckdb"
        con = duckdb.connect(str(path))
        con.execute("CREATE SCHEMA marts")
        con.execute("CREATE TABLE marts.fct_mot_tests AS SELECT DATE '2024-03-01' AS test_date "
                    "UNION ALL SELECT DATE '2024-11-30'")
        con.execute("""CREATE TABLE marts.mart_model_year_fail_rates AS SELECT
            'a-2015' AS model_year_key, 'FORD' AS make, 'FIESTA' AS model, 2015 AS first_use_year,
            125662 AS tests, 41104 AS initial_fails, 32.71 AS initial_fail_rate_pct,
            26.1 AS final_fail_rate_pct, 32.45 AS initial_fail_rate_low_pct,
            32.97 AS initial_fail_rate_high_pct, 32.70 AS estimated_initial_fail_rate_pct,
            32.44 AS estimated_low_pct, 32.96 AS estimated_high_pct,
            70000 AS median_mileage, 120000 AS mileage_readings, 3000 AS miles_per_year_p10,
            5000 AS miles_per_year_p25, 6900 AS miles_per_year_p50, 9000 AS miles_per_year_p75,
            12000 AS miles_per_year_p90, 1900000 AS peer_tests, 26.52 AS peer_initial_fail_rate_pct,
            21.3 AS peer_final_fail_rate_pct, 6.19 AS initial_fail_rate_vs_peers_pts,
            3.1 AS peer_between_model_sd_pts, 20.4 AS funnel_low_95_pct, 32.6 AS funnel_high_95_pct,
            16.9 AS funnel_low_998_pct, 36.1 AS funnel_high_998_pct, 'higher' AS vs_peers,
            'inside' AS funnel_position""")
        con.execute("""CREATE TABLE marts.mart_model_year_defect_categories AS SELECT
            'a-2015' AS model_year_key, 'Brakes' AS defect_category, 9000 AS tests_with_failure_item,
            12000 AS tests_with_advisory, 7.2 AS failure_share_pct, 7.0 AS failure_share_low_pct,
            9.5 AS advisory_share_pct, 6.1 AS peer_failure_share_pct, 8.8 AS peer_advisory_share_pct""")
        con.execute("""CREATE TABLE marts.mart_odometer_rounding AS SELECT
            'last_digit-0' AS check_key, 'last_digit' AS check_name, '0' AS pattern,
            1200 AS readings, 10000 AS total_readings, 12.0 AS share_pct, 10.0 AS expected_share_pct""")
        con.close()
        return path

    def test_loads_marts_and_is_safe_to_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_warehouse(folder)
            out = StringIO()
            call_command("load_mot_marts", warehouse=str(path), stdout=out)
            call_command("load_mot_marts", warehouse=str(path), stdout=StringIO())
        self.assertIn("Loaded 1 model-year groups and 1 defect-category rows", out.getvalue())
        self.assertEqual(ModelYearFailRate.objects.count(), 1)
        self.assertEqual(ModelYearDefectCategory.objects.count(), 1)
        self.assertEqual(OdometerRounding.objects.count(), 1)
        row = ModelYearFailRate.objects.get()
        self.assertEqual((row.make, row.first_use_year, row.test_year), ("FORD", 2015, 2024))
        self.assertEqual((row.vs_peers, row.miles_per_year_p50), ("higher", 6900))
        self.assertEqual((row.make_slug, row.model_slug), ("ford", "fiesta"))

    def test_missing_warehouse_is_a_clear_error(self):
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, "Warehouse not found"):
            call_command("load_mot_marts", warehouse="nowhere/mot.duckdb")


class ComparisonTests(TestCase):
    def test_finds_group_despite_case_and_spaces(self):
        rate = make_rate()
        add_category(rate, "Lamps", 9.0, 5.5)
        add_category(rate, "Brakes", 7.0, 6.5)
        c = build_comparison({"make": "ford", "model": " fiesta ", "first_used": datetime(2016, 3, 15)})
        self.assertTrue(c["found"])
        self.assertEqual(c["plural"], "Ford Fiestas")
        self.assertEqual(c["verdict"], "more often than")
        self.assertEqual([x["name"] for x in c["categories"]], ["Lamps", "Brakes"])  # biggest first
        self.assertTrue(c["categories"][0]["higher"])      # 3.5 points above peers
        self.assertFalse(c["categories"][1]["higher"])     # 0.5 points: not highlighted

    def test_verdict_comes_from_the_statistics_not_the_size_of_the_gap(self):
        # 6 points above peers, but only 40 tests: dbt said 'within', so not called worse
        make_rate(tests=40, initial_fail_rate_vs_peers_pts=6.0, vs_peers="within",
                  funnel_position="inside")
        c = build_comparison(FIESTA_2016)
        self.assertEqual(c["verdict"], "not clearly more or less often than")
        self.assertIn("too few tests", c["verdict_note"])
        self.assertFalse(c["worse"])

    def test_big_groups_inside_the_funnel_are_still_called_worse_when_they_are(self):
        # a popular model can be clearly above average yet within the normal spread of models
        make_rate(vs_peers="higher", funnel_position="inside")
        c = build_comparison(FIESTA_2016)
        self.assertEqual(c["verdict"], "more often than")
        self.assertIn("within the usual range", c["verdict_note"])

    def test_big_groups_with_a_tiny_gap_are_about_the_same(self):
        make_rate(vs_peers="within", funnel_position="inside")
        self.assertEqual(build_comparison(FIESTA_2016)["verdict"], "about as often as")

    def test_small_groups_show_the_adjusted_estimate(self):
        make_rate(tests=40, vs_peers="within", funnel_position="inside", initial_fail_rate_low_pct=25.0,
                  initial_fail_rate_high_pct=55.0, estimated_initial_fail_rate_pct=29.4)
        self.assertTrue(build_comparison(FIESTA_2016)["small_group"])
        make_rate(model_year_key="big", model="FOCUS")
        c = build_comparison({**FIESTA_2016, "model": "FOCUS"})
        self.assertFalse(c["small_group"])

    def test_category_needs_its_whole_range_above_peers_to_be_highlighted(self):
        rate = make_rate()
        add_category(rate, "Brakes", 9.0, 6.0, low=5.5)   # 3 points above, but range dips below
        self.assertFalse(build_comparison(FIESTA_2016)["categories"][0]["higher"])

    def test_no_group_means_not_found(self):
        make_rate(model_year_key="other", model="FOCUS")
        c = build_comparison(FIESTA_2016)
        self.assertFalse(c["found"])
        self.assertFalse(c["too_new"])                       # 2016 cars exist, just not this one

    def test_cars_newer_than_any_group_are_too_new_to_compare(self):
        make_rate()                                          # youngest group: 2016
        c = build_comparison({**FIESTA_2016, "first_used": datetime(2024, 5, 1)})
        self.assertTrue(c["too_new"])

    def test_hyphenated_makes_are_capitalised_on_both_sides(self):
        from .comparison import _display_name
        self.assertEqual(_display_name("MERCEDES-BENZ A CLASS"), "Mercedes-Benz A Class")

    def test_plural_for_number_models(self):
        make_rate()
        c = build_comparison({"make": "BMW", "model": "3 SERIES", "first_used": datetime(2016, 1, 1)})
        self.assertEqual(c["plural"], "BMW 3 Series cars")

    def test_funnel_needs_enough_models_and_highlights_this_one(self):
        make_rate()
        self.assertIsNone(build_comparison(FIESTA_2016)["funnel"])     # 1 model: nothing to show
        for i in range(6):
            make_rate(model_year_key=f"m{i}", model=f"MODEL {i}", tests=50 * 10 ** (i % 4),
                      initial_fail_rate_pct=15 + 3 * i, vs_peers="within",
                      funnel_position="inside")
        f = build_comparison(FIESTA_2016)["funnel"]
        self.assertEqual(f["models"], 7)
        self.assertEqual(len(f["points"]), 6)                          # the others; this one apart
        self.assertTrue(f["inner"][0].startswith("M"))
        for p in f["points"] + [f["this"]]:
            self.assertTrue(f["plot"]["left"] <= p["x"] <= f["plot"]["right"])
            self.assertTrue(f["plot"]["top"] <= p["y"] <= f["plot"]["bottom"])


class PositionAmongModelsTests(TestCase):
    def setUp(self):
        self.fiesta = make_rate(estimated_initial_fail_rate_pct=31.0)
        for i in range(9):                         # nine other 2016 models, 20% to 28%
            make_rate(model_year_key=f"m{i}", model=f"MODEL {i}", model_slug=f"model-{i}",
                      estimated_initial_fail_rate_pct=20 + i)

    def test_headline_counts_models_that_fail_less_often(self):
        pos = build_comparison(FIESTA_2016)["position"]
        self.assertEqual(pos["headline"], "Fails more often than almost every other model")
        make_rate(model_year_key="worse", model="WORSE", model_slug="worse",
                  estimated_initial_fail_rate_pct=40.0)
        pos = build_comparison(FIESTA_2016)["position"]
        self.assertEqual(pos["headline"], "Fails more often than 9 in 10 other models")

    def test_scale_positions_stay_on_the_scale(self):
        pos = build_comparison(FIESTA_2016)["position"]
        for key in ("this", "peer", "band_left"):
            self.assertTrue(0 <= pos["pos"][key] <= 100)
        self.assertLessEqual(pos["pos"]["band_left"] + pos["pos"]["band_width"], 100.01)
        self.assertEqual(pos["align"]["this"], "middle")

    def test_needs_a_few_models_to_compare_with(self):
        ModelYearFailRate.objects.exclude(pk=self.fiesta.pk).delete()
        self.assertIsNone(build_comparison(FIESTA_2016)["position"])


class MileageComparisonTests(TestCase):
    def band(self, miles, **row):
        return mileage_comparison(make_rate(**row), miles, "2016 Ford Fiestas")

    def test_bands(self):
        self.assertEqual(self.band(2000)["band"], "low")
        ModelYearFailRate.objects.all().delete()
        self.assertEqual(self.band(4000)["band"], "below")
        ModelYearFailRate.objects.all().delete()
        self.assertEqual(self.band(7000)["band"], "typical")
        ModelYearFailRate.objects.all().delete()
        self.assertEqual(self.band(10000)["band"], "above")
        ModelYearFailRate.objects.all().delete()
        self.assertEqual(self.band(20000)["band"], "high")

    def test_low_mileage_suggests_checking_records(self):
        self.assertIn("service records", self.band(2000)["text"])

    def test_not_shown_without_enough_readings_or_a_rate(self):
        self.assertIsNone(self.band(7000, mileage_readings=10))
        ModelYearFailRate.objects.all().delete()
        self.assertIsNone(self.band(None))

    def test_report_works_out_miles_per_year_since_new(self):
        # SAMPLE1: first used 15 Mar 2016, 73,410 miles on 4 Mar 2025 (3,276 days)
        summary = build_report(load_sample("SAMPLE1"))["summary"]
        self.assertEqual(summary["miles_per_year_since_new"], round(73410 / (3276 / 365.25)))

    def test_no_mileage_rate_when_the_mileage_went_down(self):
        summary = build_report(load_sample("SAMPLE2"))["summary"]   # Golf with a mileage drop
        self.assertIsNone(summary["miles_per_year_since_new"])


@override_settings(DVSA_CLIENT_ID="")
class ReportComparisonPageTests(TestCase):
    def test_report_shows_comparison_when_group_exists(self):
        rate = make_rate()                         # SAMPLE1 is a 2016 Ford Fiesta
        add_category(rate, "Lamps", 9.0, 5.5)
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, "Compared with other cars like this")
        self.assertContains(response, "All 2016 cars")
        self.assertContains(response, "more often than")
        self.assertContains(response, "miles a year")             # mileage comparison shown
        self.assertContains(response, "Open Government Licence v3.0")

    def test_report_draws_the_funnel(self):
        make_rate()
        for i in range(6):
            make_rate(model_year_key=f"m{i}", model=f"MODEL {i}", tests=100 * (i + 1),
                      initial_fail_rate_pct=20 + i, vs_peers="within",
                      funnel_position="inside")
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, 'class="funnel-this"')
        self.assertContains(response, "Failure rates of 7 models first used in 2016")

    def test_report_explains_when_there_is_too_little_data(self):
        make_rate(model_year_key="other", model="FOCUS")   # marts loaded, but no 2016 Fiesta group
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, "weren't enough MOT tests")

    def test_section_is_hidden_until_marts_are_loaded(self):
        response = self.client.get("/report/SAMPLE1/")
        self.assertNotContains(response, "Compared with other cars like this")
