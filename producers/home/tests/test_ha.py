import unittest

from helpers import TOKEN, FakeHA

import socket

from home_producer.ha import Client, HAError, prefer_ipv4

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



class PreferIPv4(unittest.TestCase):

    def resolver(self, *addresses):
        calls = []

        def resolve(host, port, family, kind):
            calls.append((host, port, family))
            return [(family, kind, 6, "", (a, port)) for a in addresses]
        resolve.calls = calls
        return resolve

    def test_a_name_goes_over_its_ipv4_address_with_the_original_host(self):
        resolve = self.resolver("192.168.139.172")
        url, host = prefer_ipv4("http://homeassistant.lan:8123/api/states", resolve)
        self.assertEqual((url, host), ("http://192.168.139.172:8123/api/states", "homeassistant.lan:8123"))
        self.assertEqual(resolve.calls, [("homeassistant.lan", 8123, socket.AF_INET)])

    def test_query_strings_and_default_ports_survive(self):
        url, host = prefer_ipv4("http://ha.lan/api/services/weather/get_forecasts?return_response",
                                self.resolver("10.0.0.5"))
        self.assertEqual((url, host), ("http://10.0.0.5/api/services/weather/get_forecasts?return_response",
                                       "ha.lan"))

    def test_left_alone(self):
        def no_ipv4(*args):
            raise socket.gaierror("no A record")
        for url, resolve in (("https://ha.example.com/api/", self.resolver("10.0.0.5")),
                             ("http://192.168.139.172:8123/api/", self.resolver("10.0.0.5")),
                             ("http://[2601:188::1]:8123/api/", self.resolver("10.0.0.5")),
                             ("http://v6only.lan:8123/api/", no_ipv4)):
            self.assertEqual(prefer_ipv4(url, resolve), (url, None))


if __name__ == "__main__":
    unittest.main()
