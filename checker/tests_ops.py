"""Tests for running the live site: health check, lookup limits, logging and error emails."""

import logging
import http.client
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings

from . import dvsa, ratelimit
from .tests_dvsa import FAKE_SETTINGS, TOKEN, VEHICLE

# A fixed clock, so a test never straddles two one-minute windows.
FROZEN_TIME = mock.patch("checker.ratelimit.time.time", return_value=1_800_000_000.0)


class HealthCheckTests(TestCase):
    def test_answers_ok_and_is_never_cached(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(ALLOWED_HOSTS=["carverse.example"], SECURE_SSL_REDIRECT=True)
    def test_works_with_any_host_name_and_plain_http(self):
        # Render may check from an internal address over plain http.
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="10.0.0.7").status_code, 200)
        # ...while ordinary pages still refuse an unknown host.
        self.assertEqual(self.client.get("/", HTTP_HOST="10.0.0.7").status_code, 400)

    def test_does_not_touch_the_database(self):
        with self.assertNumQueries(0):
            self.client.get("/healthz")


@override_settings(**FAKE_SETTINGS)
class LookupLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(PLATE_LOOKUPS_PER_MINUTE=2)
    def test_a_visitor_over_the_limit_is_asked_to_wait(self):
        with FROZEN_TIME, mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]):
            self.assertEqual(self.client.get("/report/AB12CDE/").status_code, 200)
            self.assertEqual(self.client.get("/report/AB12CDE/").status_code, 200)
            with self.assertLogs("checker.views", "WARNING"):
                response = self.client.get("/report/AB12CDE/")
        self.assertContains(response, "a lot of checks in one minute", status_code=429)
        self.assertTrue(response.has_header("Retry-After"))

    @override_settings(PLATE_LOOKUPS_PER_MINUTE=1)
    def test_demo_cars_are_never_limited(self):
        with FROZEN_TIME:
            for _ in range(3):
                self.assertEqual(self.client.get("/report/SAMPLE1/").status_code, 200)

    @override_settings(PLATE_LOOKUPS_PER_MINUTE=1)
    def test_visitors_are_counted_separately(self):
        with FROZEN_TIME, mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]):
            self.assertEqual(self.client.get("/report/AB12CDE/", REMOTE_ADDR="198.51.100.1").status_code, 200)
            self.assertEqual(self.client.get("/report/AB12CDE/", REMOTE_ADDR="198.51.100.2").status_code, 200)

    def test_the_visitor_is_the_first_forwarded_address(self):
        factory = RequestFactory()
        behind_proxy = factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", REMOTE_ADDR="10.0.0.1")
        direct = factory.get("/", REMOTE_ADDR="203.0.113.9")
        self.assertEqual(ratelimit.visitor_id(behind_proxy), ratelimit.visitor_id(direct))

    def test_ip_addresses_are_scrambled(self):
        request = RequestFactory().get("/", REMOTE_ADDR="203.0.113.9")
        self.assertNotIn("203.0.113", ratelimit.visitor_id(request))

    @override_settings(DVSA_CALLS_PER_MINUTE=1)
    def test_site_wide_limit_on_dvsa_calls(self):
        with FROZEN_TIME, mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]) as send:
            self.assertEqual(self.client.get("/report/AB12CDE/").status_code, 200)
            with self.assertLogs("checker.dvsa", "WARNING"), self.assertLogs("django.request", "ERROR"):
                response = self.client.get("/report/XY34ZZZ/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(send.call_count, 2)                # the token and the first car only


@override_settings(**FAKE_SETTINGS)
class LoggingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_refused_credentials_are_logged_as_an_error(self):
        with mock.patch.object(dvsa, "_send", side_effect=[(400, {"error": "invalid_client"})]):
            with self.assertLogs("checker.dvsa", "ERROR") as logs, self.assertRaises(dvsa.DvsaUnavailable):
                dvsa.get_vehicle("AB12CDE")
        self.assertIn("Check the DVSA_* credentials", logs.output[0])

    def test_logs_never_contain_the_plate_or_credentials(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (500, None)]):
            with self.assertLogs("checker", "DEBUG") as logs, self.assertRaises(dvsa.DvsaUnavailable):
                dvsa.get_vehicle("AB12CDE")
        text = "\n".join(logs.output)
        self.assertIn("HTTP 500", text)
        for secret in ["AB12CDE", "tok-1", FAKE_SETTINGS["DVSA_CLIENT_SECRET"]]:
            self.assertNotIn(secret, text)


@override_settings(ADMINS=["owner@example.com"])
class ErrorEmailTests(TestCase):
    def setUp(self):
        cache.clear()
        # Keep the expected tracebacks out of the test output; the email handler stays.
        logger = logging.getLogger("django")
        quiet = [h for h in logger.handlers if not isinstance(h, logging.StreamHandler)]
        patcher = mock.patch.object(logger, "handlers", quiet)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unexpected_errors_are_emailed(self):
        client = Client(raise_request_exception=False)
        with mock.patch("checker.views.build_report", side_effect=RuntimeError("boom")):
            response = client.get("/report/SAMPLE1/")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])

    @override_settings(**FAKE_SETTINGS)
    def test_dvsa_being_down_is_not_emailed(self):
        with mock.patch.object(dvsa, "_send", side_effect=dvsa.DvsaUnavailable("network")):
            response = self.client.get("/report/AB12CDE/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(mail.outbox, [])


@override_settings(**FAKE_SETTINGS)
class ConfigurationMistakeTests(TestCase):
    """The live site once had DVSA_TOKEN_URL pasted with the next line of .env attached."""

    def setUp(self):
        cache.clear()

    @override_settings(DVSA_TOKEN_URL="https://login.example/token\nDJANGO_DEBUG=1")
    def test_a_line_break_in_a_setting_shows_the_try_again_page(self):
        with mock.patch.object(dvsa, "_send") as send:
            with self.assertLogs("checker.dvsa", "ERROR") as logs, self.assertLogs("django.request", "ERROR"):
                response = self.client.get("/report/AB12CDE/")
        self.assertEqual(response.status_code, 503)
        send.assert_not_called()
        self.assertIn("DVSA_TOKEN_URL", logs.output[0])
        self.assertNotIn("login.example", logs.output[0])     # names the setting, never its value

    @override_settings(DVSA_API_KEY=" key")
    def test_spaces_at_either_end_are_caught_too(self):
        with self.assertLogs("checker.dvsa", "ERROR"), self.assertRaises(dvsa.DvsaUnavailable):
            dvsa.get_vehicle("AB12CDE")

    def test_odd_network_failures_are_treated_as_dvsa_unavailable(self):
        for failure in [http.client.InvalidURL("bad"), http.client.RemoteDisconnected("gone"),
                        ConnectionResetError(), http.client.IncompleteRead(b"")]:
            cache.clear()
            with self.subTest(failure=type(failure).__name__):
                with mock.patch("urllib.request.urlopen", side_effect=failure):
                    with self.assertLogs("checker.dvsa", "WARNING"), self.assertRaises(dvsa.DvsaUnavailable):
                        dvsa.get_vehicle("AB12CDE")
