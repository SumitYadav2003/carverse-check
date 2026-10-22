"""Tests for the mart loader and the "Compared with other cars like this" section."""

import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

import duckdb
from django.core.management import call_command
from django.test import TestCase

from .comparison import build_comparison
from .models import ModelYearDefectCategory, ModelYearFailRate


def make_rate(**overrides):
    values = dict(model_year_key="k-2016", make="FORD", model="FIESTA", first_use_year=2016,
                  test_year=2024, tests=114221, initial_fail_rate_pct=31.28,
                  final_fail_rate_pct=25.0, median_mileage=60000, peer_tests=2_000_000,
                  peer_initial_fail_rate_pct=23.33, peer_final_fail_rate_pct=19.0,
                  initial_fail_rate_vs_peers_pts=7.95)
    values.update(overrides)
    return ModelYearFailRate.objects.create(**values)


def add_category(rate, name, share, peer):
    return ModelYearDefectCategory.objects.create(
        model_year=rate, defect_category=name, tests_with_failure_item=1,
        tests_with_advisory=1, failure_share_pct=share, advisory_share_pct=1.0,
        peer_failure_share_pct=peer, peer_advisory_share_pct=1.0)


class LoaderTests(TestCase):
    def make_warehouse(self, folder):
        path = Path(folder) / "mot.duckdb"
        con = duckdb.connect(str(path))
        con.execute("CREATE SCHEMA marts")
        con.execute("CREATE TABLE marts.fct_mot_tests AS SELECT DATE '2024-03-01' AS test_date "
                    "UNION ALL SELECT DATE '2024-11-30'")
        con.execute("""CREATE TABLE marts.mart_model_year_fail_rates AS SELECT
            'a-2015' AS model_year_key, 'FORD' AS make, 'FIESTA' AS model, 2015 AS first_use_year,
            125662 AS tests, 32.71 AS initial_fail_rate_pct, 26.1 AS final_fail_rate_pct,
            70000 AS median_mileage, 1900000 AS peer_tests, 26.52 AS peer_initial_fail_rate_pct,
            21.3 AS peer_final_fail_rate_pct, 6.19 AS initial_fail_rate_vs_peers_pts""")
        con.execute("""CREATE TABLE marts.mart_model_year_defect_categories AS SELECT
            'a-2015' AS model_year_key, 'Brakes' AS defect_category, 9000 AS tests_with_failure_item,
            12000 AS tests_with_advisory, 7.2 AS failure_share_pct, 9.5 AS advisory_share_pct,
            6.1 AS peer_failure_share_pct, 8.8 AS peer_advisory_share_pct""")
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
        row = ModelYearFailRate.objects.get()
        self.assertEqual((row.make, row.first_use_year, row.test_year), ("FORD", 2015, 2024))

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

    def test_small_differences_are_called_about_the_same(self):
        make_rate(initial_fail_rate_vs_peers_pts=0.6)
        c = build_comparison({"make": "FORD", "model": "FIESTA", "first_used": datetime(2016, 1, 1)})
        self.assertEqual(c["verdict"], "about as often as")

    def test_no_group_means_not_found(self):
        make_rate(model_year_key="other", model="FOCUS")
        c = build_comparison({"make": "FORD", "model": "FIESTA", "first_used": datetime(2016, 1, 1)})
        self.assertFalse(c["found"])

    def test_plural_for_number_models(self):
        make_rate()
        c = build_comparison({"make": "BMW", "model": "3 SERIES", "first_used": datetime(2016, 1, 1)})
        self.assertEqual(c["plural"], "BMW 3 Series cars")


class ReportComparisonPageTests(TestCase):
    def test_report_shows_comparison_when_group_exists(self):
        rate = make_rate()                         # SAMPLE1 is a 2016 Ford Fiesta
        add_category(rate, "Lamps", 9.0, 5.5)
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, "Compared with other cars like this")
        self.assertContains(response, "All 2016 cars")
        self.assertContains(response, "more often than")
        self.assertContains(response, "Open Government Licence v3.0")

    def test_report_explains_when_there_is_too_little_data(self):
        make_rate(model_year_key="other", model="FOCUS")   # marts loaded, but no 2016 Fiesta group
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, "weren't enough MOT tests")

    def test_section_is_hidden_until_marts_are_loaded(self):
        response = self.client.get("/report/SAMPLE1/")
        self.assertNotContains(response, "Compared with other cars like this")
