from datetime import datetime

from django.test import SimpleTestCase

from .analysis import build_report, normalise_defect_text, parse_datetime, mileage_in_miles
from .sample_data import load_sample


def codes(report):
    return [f["code"] for f in report["findings"]]


class ParsingTests(SimpleTestCase):
    def test_parses_all_dvsa_date_styles(self):
        expected = datetime(2016, 6, 21, 11, 26, 2)
        self.assertEqual(parse_datetime("2016-06-21 11:26:02"), expected)
        self.assertEqual(parse_datetime("2016.06.21 11:26:02"), expected)
        self.assertEqual(parse_datetime("2016-06-21T11:26:02.000Z"), expected)
        self.assertEqual(parse_datetime("2017-06-28"), datetime(2017, 6, 28))

    def test_unreadable_odometer_is_ignored(self):
        self.assertIsNone(mileage_in_miles({"odometerValue": "5000", "odometerResultType": "UNREADABLE"}))

    def test_kilometres_are_converted_to_miles(self):
        self.assertEqual(mileage_in_miles({"odometerValue": "10000", "odometerUnit": "KM"}), 6214)

    def test_manual_reference_is_removed_from_defect_text(self):
        self.assertEqual(
            normalise_defect_text("Offside rear brake pipe corroded (1.1.11 (c))"),
            "offside rear brake pipe corroded",
        )


class SampleVehicleTests(SimpleTestCase):
    def test_clean_car_has_no_findings(self):
        report = build_report(load_sample("SAMPLE1"))
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["failed_count"], 1)   # headlamp fail, passed on retest
        self.assertEqual(report["summary"]["latest_miles"], 73410)

    def test_mileage_decrease_is_flagged_with_both_tests_as_evidence(self):
        report = build_report(load_sample("SAMPLE2"))
        self.assertEqual(codes(report), ["mileage_decrease"])
        evidence = report["findings"][0]["evidence"]
        self.assertEqual([e["test_number"] for e in evidence], ["200000000105", "200000000106"])
        self.assertIsNone(report["summary"]["avg_miles_per_year"])  # not trustworthy here

    def test_problem_car_flags_danger_repeats_and_gap(self):
        report = build_report(load_sample("SAMPLE3"))
        found = codes(report)
        self.assertEqual(found[0], "dangerous_defect")            # high severity sorted first
        self.assertEqual(found.count("repeated_advisory"), 2)     # offside and nearside pipes
        self.assertIn("test_gap", found)
        offside = next(f for f in report["findings"]
                       if f["code"] == "repeated_advisory" and "offside" in f["detail"].lower())
        self.assertEqual(len(offside["evidence"]), 3)            # 2019, 2020, 2021

    def test_unreadable_reading_does_not_cause_false_alarm(self):
        report = build_report(load_sample("SAMPLE3"))
        self.assertNotIn("mileage_decrease", codes(report))

    def test_unknown_registration_returns_none(self):
        self.assertIsNone(load_sample("NOTREAL"))


class PageTests(SimpleTestCase):
    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Know the car before you meet the seller.")

    def test_plate_is_cleaned_and_redirected(self):
        response = self.client.get("/check/", {"reg": " sample 3 "})
        self.assertRedirects(response, "/report/SAMPLE3/", fetch_redirect_response=False)

    def test_invalid_plate_shows_an_error(self):
        response = self.client.get("/check/", {"reg": "!!!"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "doesn&#x27;t look like a UK number plate", status_code=400)

    def test_report_shows_findings_and_links_evidence_to_the_timeline(self):
        response = self.client.get("/report/SAMPLE3/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dangerous defect recorded")
        self.assertContains(response, 'href="#t-300000000106"')   # evidence chip...
        self.assertContains(response, 'id="t-300000000106"')      # ...points at a real timeline row
        self.assertContains(response, "Sample vehicle")

    def test_clean_car_says_all_clear(self):
        response = self.client.get("/report/SAMPLE1/")
        self.assertContains(response, "No red flags in the MOT history.")
        self.assertContains(response, "Pass · retest")

    def test_mileage_drop_hides_average_and_draws_orange_segment(self):
        response = self.client.get("/report/SAMPLE2/")
        self.assertContains(response, "average not shown")
        self.assertContains(response, 'class="seg-drop draw"')

    def test_unknown_plate_is_a_friendly_404(self):
        response = self.client.get("/report/NOTREAL/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "couldn't find that car", status_code=404)

    def test_unreadable_reading_is_not_drawn_as_a_gap(self):
        response = self.client.get("/report/SAMPLE3/")
        self.assertEqual(response.content.decode().count('class="seg-gap"'), 1)   # only the 2021-2023 gap
