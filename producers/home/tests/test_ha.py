import unittest

from helpers import TOKEN, FakeHA

from home_producer.ha import Client, HAError

URL = "http://ha.test:8123"


class ClientTest(unittest.TestCase):

    def test_states_sends_the_token_and_returns_the_list(self):
        fake = FakeHA()
        states = Client(URL + "/", TOKEN, fake).states()
        self.assertIn("weather.home", {s["entity_id"] for s in states})
        self.assertEqual(fake.calls[0][:2], ("GET", URL + "/api/states"))

    def test_states_drops_entries_without_an_entity_id(self):
        fake = FakeHA(states_doc=[{"entity_id": "sun.sun", "state": "above_horizon"}, {"state": "x"}, "junk"])
        self.assertEqual([s["entity_id"] for s in Client(URL, TOKEN, fake).states()], ["sun.sun"])

    def test_a_rejected_token_is_named_but_never_shown(self):
        with self.assertRaises(HAError) as caught:
            Client(URL, "wrong-token", FakeHA()).states()
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("wrong-token", str(caught.exception))

    def test_network_failure(self):
        fake = FakeHA()
        fake.down = True
        with self.assertRaisesRegex(HAError, "unreachable"):
            Client(URL, TOKEN, fake).states()

    def test_not_json(self):
        with self.assertRaisesRegex(HAError, "not JSON"):
            Client(URL, TOKEN, lambda *a, **k: (200, b"<html>")).states()

    def test_forecast_posts_get_forecasts_and_unwraps_the_response(self):
        fake = FakeHA()
        hourly = Client(URL, TOKEN, fake).forecast("weather.home", "hourly")
        self.assertEqual(len(hourly), 24)
        method, url, body = fake.calls[0]
        self.assertEqual((method, body), ("POST", {"entity_id": "weather.home", "type": "hourly"}))
        self.assertTrue(url.endswith("/api/services/weather/get_forecasts?return_response"))

    def test_forecast_for_another_entity_is_an_error(self):
        with self.assertRaisesRegex(HAError, "no daily forecast for weather.other"):
            Client(URL, TOKEN, FakeHA()).forecast("weather.other", "daily")


if __name__ == "__main__":
    unittest.main()
