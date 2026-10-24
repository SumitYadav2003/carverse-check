from datetime import datetime

from django.test import SimpleTestCase, TestCase, override_settings

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


# Live DVSA lookups are switched off here: tests must never call the real API.
@override_settings(DVSA_CLIENT_ID="")
class PageTests(TestCase):   # the report page now reads the marts from the database
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


@override_settings(DVSA_CLIENT_ID="")
class SitePageTests(TestCase):
    """Every content page renders, is linked from the footer, and nothing sets a cookie
    (the privacy notice promises no cookies)."""

    PAGES = ["how_it_works", "methodology", "help", "about", "privacy", "terms",
             "accessibility", "contact"]

    def test_every_page_renders_with_header_and_footer(self):
        from django.urls import reverse
        home = self.client.get("/")
        for name in self.PAGES:
            url = reverse(f"checker:{name}")
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="site-header"')
                self.assertContains(response, "Open Government Licence v3.0")
                self.assertContains(home, f'href="{url}"')          # reachable from every page

    def test_current_page_is_marked_in_the_menu(self):
        response = self.client.get("/methodology/")
        self.assertContains(response, 'href="/methodology/" aria-current="page"')

    def test_contact_email_is_shown(self):
        self.assertContains(self.client.get("/contact/"), "culinaai.project@gmail.com")

    def test_no_page_sets_a_cookie(self):
        for url in ["/", "/report/SAMPLE1/", "/privacy/", "/methodology/", "/report/NOSUCHCAR/"]:
            with self.subTest(url=url):
                self.assertEqual(len(self.client.get(url).cookies), 0)

    def test_reports_are_kept_out_of_search_engines(self):
        self.assertContains(self.client.get("/report/SAMPLE1/"), '<meta name="robots" content="noindex">')
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots["Content-Type"], "text/plain")
        self.assertIn("Disallow: /report/", robots.content.decode())

    def test_report_has_sidebar_actions(self):
        response = self.client.get("/report/SAMPLE3/")
        self.assertContains(response, "data-print")
        self.assertContains(response, "data-copy-link")
        self.assertContains(response, 'href="#history"')

    @override_settings(DEBUG=False)
    def test_unknown_address_uses_the_site_404_page(self):
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "This page doesn't exist", status_code=404)

    def test_methodology_shows_odometer_check_once_loaded(self):
        from .models import OdometerRounding
        self.assertContains(self.client.get("/methodology/"), "appear here once")
        for digit in range(10):
            OdometerRounding.objects.create(
                check_key=f"last_digit-{digit}", check_name="last_digit", pattern=str(digit),
                readings=1000 + (500 if digit == 0 else 0), total_readings=10500,
                share_pct=(1500 if digit == 0 else 1000) / 105, expected_share_pct=10.0)
        response = self.client.get("/methodology/")
        self.assertContains(response, "10,500 MOT odometer readings")
        self.assertContains(response, "digit-bar is-over")                # 0 is over-represented


class MotStatusTests(SimpleTestCase):
    """The MOT status line at the top of a report."""

    TODAY = datetime(2026, 10, 24).date()

    def status(self, *tests, first_due=None):
        from .presenters import mot_status
        return mot_status(list(tests), first_due, self.TODAY)

    @staticmethod
    def record(result, expiry=None):
        return {"result": result, "expiry": datetime.fromisoformat(expiry) if expiry else None}

    def test_valid_mot_counts_days_left(self):
        s = self.status(self.record("PASSED", "2027-03-14"))
        self.assertEqual((s["state"], s["days"]), ("valid", 141))
        self.assertIn("valid until 14 Mar 2027", s["text"])

    def test_due_within_a_month_is_flagged(self):
        s = self.status(self.record("PASSED", "2026-11-10"))
        self.assertEqual(s["state"], "due_soon")
        self.assertIn("new MOT", s["note"])

    def test_expired_mot(self):
        s = self.status(self.record("PASSED", "2026-03-14"))
        self.assertEqual((s["state"], s["days"]), ("expired", 224))
        self.assertIn("booked MOT test", s["note"])

    def test_uses_the_latest_pass_not_a_later_failure(self):
        s = self.status(self.record("PASSED", "2027-01-05"), self.record("FAILED"))
        self.assertEqual(s["date"], "05 Jan 2027")

    def test_new_car_uses_first_due_date(self):
        s = self.status(first_due=datetime(2027, 5, 1))
        self.assertEqual((s["state"], s["date"]), ("first_due", "01 May 2027"))

    def test_nothing_known(self):
        self.assertIsNone(self.status())


@override_settings(DVSA_CLIENT_ID="")
class HeaderTests(TestCase):
    def test_header_has_example_report_and_theme_switch(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="/report/SAMPLE3/">Example report</a>')
        self.assertContains(response, "data-theme-toggle")

    def test_report_shows_mot_status(self):
        self.assertContains(self.client.get("/report/SAMPLE1/"), 'class="mot-status')
