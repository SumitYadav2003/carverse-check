"""Tests for the Explore models pages and the seller checklist."""

from datetime import datetime

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.text import slugify

from .analysis import build_report
from .checklist import build_checklist, category_for_section, manual_section, practical_check
from .explore import display, rankings
from .sample_data import load_sample
from .tests_marts import make_rate


def rate(make, model, year, tests, estimate, raw=None, **extra):
    return make_rate(model_year_key=f"{make}-{model}-{year}", make=make, model=model,
                     make_slug=slugify(make), model_slug=slugify(model), first_use_year=year,
                     tests=tests, estimated_initial_fail_rate_pct=estimate,
                     estimated_low_pct=estimate - 2, estimated_high_pct=estimate + 2,
                     initial_fail_rate_pct=estimate if raw is None else raw, **extra)


class RankingTests(TestCase):
    def setUp(self):
        # a tiny group with an extreme raw rate, and big groups with steadier ones
        rate("TINY", "ONE", 2016, 35, estimate=27.0, raw=45.0)
        for i in range(12):
            rate("BIG", f"M{i}", 2016, 5000, estimate=20.0 + i)

    def test_ranks_by_adjusted_estimate_not_raw_rate(self):
        r = rankings(2016)
        self.assertEqual(r["worst"][0]["name"], display("BIG", "M11"))   # highest adjusted estimate
        self.assertNotIn(display("TINY", "ONE"), [x["name"] for x in r["worst"][:3]])

    def test_counts_small_groups_each_ranking_would_promote(self):
        r = rankings(2016)
        self.assertEqual(r["small_in_raw_top"], 1)                  # raw ranking puts it first
        self.assertEqual(r["small_in_adjusted_top"], 1)              # still in the top 10, but 7th

    def test_no_data_for_a_year(self):
        self.assertIsNone(rankings(1999))


@override_settings(DVSA_CLIENT_ID="")
class ExplorePageTests(TestCase):
    def setUp(self):
        for year, est in [(2014, 33.0), (2015, 30.5), (2016, 28.0)]:
            rate("FORD", "FIESTA", year, 50000, est)
        rate("BMW", "3 SERIES", 2016, 9000, 24.0)

    def test_index_page(self):
        response = self.client.get("/models/")
        self.assertContains(response, "How often did each model fail its MOT?")
        self.assertContains(response, 'href="/models/ford/"')

    def test_bad_year_falls_back_to_a_real_one(self):
        self.assertEqual(self.client.get("/models/?year=abc").status_code, 200)

    def test_search_is_case_insensitive_across_make_and_model(self):
        response = self.client.get("/models/", {"q": "ford fiesta"})
        self.assertContains(response, 'href="/models/ford/fiesta/"')
        self.assertContains(self.client.get("/models/", {"q": "zzzz"}), "No make or model matched")

    def test_make_page_lists_its_models(self):
        response = self.client.get("/models/bmw/")
        self.assertContains(response, 'href="/models/bmw/3-series/"')
        self.assertEqual(self.client.get("/models/nosuchmake/").status_code, 404)

    def test_model_page_shows_every_year_and_a_chart(self):
        response = self.client.get("/models/ford/fiesta/")
        self.assertContains(response, "Ford Fiesta")
        self.assertContains(response, 'class="yc-model"')
        for year in (2014, 2015, 2016):
            self.assertContains(response, f"<td>{year}</td>")
        self.assertEqual(self.client.get("/models/ford/nosuchmodel/").status_code, 404)

    def test_report_links_to_the_model_page(self):
        response = self.client.get("/report/SAMPLE1/")          # a 2016 Ford Fiesta
        self.assertContains(response, 'href="/models/ford/fiesta/"')


class ChecklistHelperTests(SimpleTestCase):
    def test_manual_section_from_defect_text(self):
        self.assertEqual(manual_section("Front brake pad(s) wearing thin (1.1.13 (a) (ii))"), 1)
        self.assertEqual(manual_section("Tyre worn close to legal limit (5.2.3 (e))"), 5)
        self.assertIsNone(manual_section("Advise service"))

    def test_section_matches_category_by_keyword(self):
        cats = ["Lamps, reflectors and electrical equipment", "Axles, wheels, tyres and suspension"]
        self.assertEqual(category_for_section(5, cats), "Axles, wheels, tyres and suspension")
        self.assertEqual(category_for_section(4, cats), "Lamps, reflectors and electrical equipment")
        self.assertIsNone(category_for_section(1, cats))           # no brake category: no guess

    def test_practical_check_has_a_fallback(self):
        self.assertIn("tyres", practical_check("Axles, wheels, tyres and suspension"))
        self.assertIn("mechanic", practical_check("Something unusual"))


class ChecklistTests(SimpleTestCase):
    COMPARISON = {"found": True, "first_use_year": 2016, "plural": "Ford Fiestas",
                  "weak_spots": ["Brakes", "Lamps, reflectors and electrical equipment"]}

    def test_questions_from_the_cars_own_findings(self):
        checklist = build_checklist(build_report(load_sample("SAMPLE3")), None)
        texts = " ".join(q["text"] for q in checklist["from_history"])
        self.assertIn("dangerous defect", texts)
        self.assertIn("receipt", texts)
        self.assertIn("was noted at 3 MOTs", texts)
        self.assertIn("SORN", texts)
        self.assertEqual(checklist["from_model"], [])               # no comparison, no model items
        self.assertEqual(len(checklist["for_any_car"]), 3)

    def test_latest_advisory_linked_to_a_model_weak_spot(self):
        vehicle = {"firstUsedDate": "2016-03-15", "make": "FORD", "model": "FIESTA", "motTests": [
            {"completedDate": "2025-03-04 10:00:00", "testResult": "PASSED", "expiryDate": "2026-03-14",
             "odometerValue": "70000", "odometerUnit": "MI", "odometerResultType": "READ",
             "motTestNumber": "1", "defects": [
                 {"type": "ADVISORY", "text": "Front brake pad(s) wearing thin (1.1.13 (a) (ii))"},
                 {"type": "ADVISORY", "text": "Oil leak, but not excessive (8.4.1 (a) (i))"}]}]}
        checklist = build_checklist(build_report(vehicle), self.COMPARISON)
        first = checklist["from_history"][0]
        self.assertTrue(first["linked"])                            # linked questions come first
        self.assertIn("2016 Ford Fiestas fail on brakes more often", first["text"])
        self.assertFalse(checklist["from_history"][1]["linked"])    # oil leak: no matching weak spot
        # brakes is already covered by the car's own advisory, so only lamps remains
        self.assertEqual(len(checklist["from_model"]), 1)
        self.assertIn("lamps", checklist["from_model"][0]["text"])

    def test_old_tests_are_not_matched_to_the_new_manual(self):
        vehicle = {"firstUsedDate": "2010-01-01", "motTests": [
            {"completedDate": "2017-03-04 10:00:00", "testResult": "PASSED", "motTestNumber": "1",
             "odometerValue": "50000", "odometerUnit": "MI", "odometerResultType": "READ",
             "defects": [{"type": "ADVISORY", "text": "Brake pipe corroded (3.6.B.2c)"}]}]}
        checklist = build_checklist(build_report(vehicle), self.COMPARISON)
        self.assertEqual(checklist["from_history"], [])


@override_settings(DVSA_CLIENT_ID="")
class ChecklistPageTests(TestCase):
    def test_report_has_the_checklist(self):
        response = self.client.get("/report/SAMPLE3/")
        self.assertContains(response, "Questions to ask the seller")
        self.assertContains(response, 'type="checkbox"')
        self.assertContains(response, 'href="#questions"')
