"""Tests for the DVSA client and the live lookup path. DVSA is simulated: no network calls."""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from . import dvsa

FAKE_SETTINGS = dict(DVSA_CLIENT_ID="id", DVSA_CLIENT_SECRET="secret", DVSA_API_KEY="key",
                     DVSA_SCOPE="https://tapi.dvsa.gov.uk/.default",
                     DVSA_TOKEN_URL="https://login.example/token")

TOKEN = (200, {"access_token": "tok-1", "expires_in": 3599})
VEHICLE = {
    "registration": "AB12CDE", "make": "FORD", "model": "FOCUS", "firstUsedDate": "2015-03-01",
    "fuelType": "Petrol", "primaryColour": "Blue", "engineSize": "1596",
    "motTests": [
        {"completedDate": "2024-03-01T10:00:00.000Z", "testResult": "PASSED",
         "expiryDate": "2025-02-28", "odometerValue": "60000", "odometerUnit": "MI",
         "odometerResultType": "READ", "motTestNumber": "555", "dataSource": "DVSA",
         "defects": [{"text": "Tyre worn close to legal limit", "type": "ADVISORY", "dangerous": False}]},
        {"completedDate": "2023-03-02T10:00:00.000Z", "testResult": "PASSED",
         "expiryDate": "2024-03-01", "odometerValue": "52000", "odometerUnit": "MI",
         "odometerResultType": "READ", "motTestNumber": "444", "dataSource": "DVSA", "defects": []},
    ],
}


def requests_made(send):
    return [c.args[0].full_url for c in send.call_args_list]


@override_settings(**FAKE_SETTINGS)
class ClientTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_token_is_cached_between_lookups(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE), (200, VEHICLE)]) as send:
            dvsa.get_vehicle("AB12CDE")
            dvsa.get_vehicle("XY99ZZZ")
        urls = requests_made(send)
        self.assertEqual(sum("login.example" in u for u in urls), 1)   # one token for two lookups

    def test_vehicle_answer_is_cached(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]) as send:
            dvsa.get_vehicle("AB12CDE")
            dvsa.get_vehicle("AB12CDE")
        self.assertEqual(send.call_count, 2)                              # token + one lookup

    def test_sends_bearer_token_and_api_key(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]) as send:
            dvsa.get_vehicle("AB12CDE")
        lookup = send.call_args_list[1].args[0]
        self.assertTrue(lookup.full_url.endswith("/v1/trade/vehicles/registration/AB12CDE"))
        self.assertEqual(lookup.get_header("Authorization"), "Bearer tok-1")
        self.assertEqual(lookup.get_header("X-api-key"), "key")

    def test_expired_token_is_refreshed_once(self):
        fresh = (200, {"access_token": "tok-2", "expires_in": 3599})
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (401, None), fresh, (200, VEHICLE)]):
            self.assertEqual(dvsa.get_vehicle("AB12CDE")["make"], "FORD")

    def test_not_found(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (404, {"errorCode": "MOTH-NF-01"})]):
            with self.assertRaises(dvsa.VehicleNotFound):
                dvsa.get_vehicle("AB12CDE")

    def test_rate_limited_is_unavailable(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (429, {"errorCode": "MOTH-RL-02"})]):
            with self.assertRaises(dvsa.DvsaUnavailable), self.assertLogs("checker.dvsa", "WARNING"):
                dvsa.get_vehicle("AB12CDE")

    def test_failed_token_request_is_unavailable(self):
        with mock.patch.object(dvsa, "_send", side_effect=[(400, {"error": "invalid_client"})]):
            with self.assertRaises(dvsa.DvsaUnavailable), self.assertLogs("checker.dvsa", "ERROR"):
                dvsa.get_vehicle("AB12CDE")


@override_settings(**FAKE_SETTINGS)
class LivePageTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_live_report(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, VEHICLE)]):
            response = self.client.get("/report/AB12CDE/")
        self.assertContains(response, "Live data from the DVSA MOT history service")
        self.assertContains(response, "Ford Focus")
        self.assertNotContains(response, "Sample vehicle")

    def test_samples_never_call_dvsa(self):
        with mock.patch.object(dvsa, "_send") as send:
            self.client.get("/report/SAMPLE1/")
        send.assert_not_called()

    def test_dvsa_down_shows_friendly_page(self):
        with mock.patch.object(dvsa, "_send", side_effect=dvsa.DvsaUnavailable("network")):
            with self.assertLogs("django.request", "ERROR"):   # logged, but not emailed (tests_ops)
                response = self.client.get("/report/AB12CDE/")
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "couldn't reach DVSA", status_code=503)

    def test_new_car_without_tests(self):
        new_car = {"registration": "NEW1", "make": "KIA", "model": "EV6",
                   "registrationDate": "2024-05-01", "motTestDueDate": "2027-04-30"}
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (200, new_car)]):
            response = self.client.get("/report/NEW1/")
        self.assertContains(response, "No MOT tests on record yet.")
        self.assertContains(response, "first MOT is due by 30 Apr 2027")

    def test_unknown_plate_is_404(self):
        with mock.patch.object(dvsa, "_send", side_effect=[TOKEN, (404, None)]):
            response = self.client.get("/report/AB12CDE/")
        self.assertEqual(response.status_code, 404)


class NotConfiguredTests(TestCase):
    @override_settings(DVSA_CLIENT_ID="")
    def test_without_credentials_only_samples_work(self):
        with mock.patch.object(dvsa, "_send") as send:
            response = self.client.get("/report/AB12CDE/")
        send.assert_not_called()
        self.assertEqual(response.status_code, 404)
