import json
import os
import shutil
import tempfile
import unittest

from helpers import TOKEN, Clock, FakeHA

from home_producer import producer
from home_producer.producer import Producer


class ProducerTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.token_file = os.path.join(self.root, "ha-token")
        self.webroot = os.path.join(self.root, "www")
        self.fake = FakeHA()
        self.clock = Clock()

    def seed_token(self, token=TOKEN):
        with open(self.token_file, "w") as fh:
            fh.write(token + "\n")

    def make(self, **kw):
        return Producer(self.webroot, self.token_file, "http://ha.test:8123", tz="America/New_York",
                        transport=self.fake, clock=self.clock, **kw)

    def pane(self, pane_id, name="manifest.json"):
        path = os.path.join(self.webroot, "viewport", "panes", pane_id, name)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) if name.endswith(".json") else fh.read()

    def test_no_token_writes_nothing_and_says_so_once(self):
        p = self.make()
        with self.assertLogs(producer.log, "WARNING") as logs:
            p.cycle()
            p.cycle()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("no Home Assistant token", logs.output[0])
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(os.path.exists(self.webroot))

    def test_a_token_puts_both_panes_on_the_bus(self):
        self.seed_token()
        self.make().cycle()
        for pane_id, title in (("home", "Home"), ("weather", "Weather")):
            manifest = self.pane(pane_id)
            self.assertEqual(manifest, {
                "schema": 1, "class": "ambient", "title": title, "created": "2026-10-29T00:40:00Z",
                "ttl_minutes": 10, "author": "home-producer@pub", "origin": "operator", "dwell_s": 60})
            self.assertIn("<!DOCTYPE html>", self.pane(pane_id, "pane.html"))
            leftovers = [f for f in os.listdir(os.path.dirname(
                os.path.join(self.webroot, "viewport", "panes", pane_id, "x"))) if f.endswith(".partial")]
            self.assertEqual(leftovers, [])
        self.assertNotIn(TOKEN, self.pane("home", "pane.html"))

    def test_a_rejected_token_or_a_dead_home_assistant_leaves_the_panes_to_their_ttl(self):
        self.seed_token()
        p = self.make()
        p.cycle()
        self.clock.advance(60)
        self.fake.down = True
        p.cycle()
        self.assertEqual(self.pane("home")["created"], "2026-10-29T00:40:00Z")   # not renewed
        self.seed_token("revoked")
        self.fake.down = False
        p.cycle()
        self.assertEqual(self.pane("weather")["created"], "2026-10-29T00:40:00Z")

    def test_forecasts_are_fetched_every_ten_minutes(self):
        self.seed_token()
        p = self.make()
        p.cycle()
        self.assertEqual(len(self.fake.forecast_calls()), 2)          # hourly and daily
        self.clock.advance(300)
        p.cycle()
        self.assertEqual(len(self.fake.forecast_calls()), 2)
        self.clock.advance(300)
        p.cycle()
        self.assertEqual(len(self.fake.forecast_calls()), 4)

    def test_a_failed_forecast_keeps_the_last_good_one_for_a_while(self):
        self.seed_token()
        p = self.make()
        p.cycle()
        self.fake.forecast_status = 500
        self.clock.advance(600)
        p.cycle()
        self.assertNotIn("No hourly forecast.", self.pane("weather", "pane.html"))
        self.clock.advance(3 * 3600)
        p.cycle()
        page = self.pane("weather", "pane.html")
        self.assertIn("No hourly forecast.", page)
        self.assertIn("No daily forecast.", page)

    def test_without_a_weather_entity_the_weather_pane_goes(self):
        self.seed_token()
        self.make().cycle()
        self.fake.states = [s for s in self.fake.states if not s["entity_id"].startswith("weather.")]
        self.make().cycle()
        self.assertIsNone(self.pane("weather"))
        self.assertIsNotNone(self.pane("home"))

    def test_a_named_weather_entity(self):
        self.seed_token()
        self.make(weather_entity="weather.elsewhere").cycle()
        self.assertIsNone(self.pane("weather"))

    def test_someone_elses_pane_is_left_alone(self):
        self.seed_token()
        other = os.path.join(self.webroot, "viewport", "panes", "weather")
        os.makedirs(other)
        with open(os.path.join(other, "manifest.json"), "w") as fh:
            json.dump({"author": "someone@else"}, fh)
        with self.assertLogs(producer.log, "WARNING") as logs:
            self.make().cycle()
        self.assertIn("belongs to 'someone@else'", logs.output[0])
        self.assertEqual(self.pane("weather"), {"author": "someone@else"})
        self.assertEqual(os.listdir(other), ["manifest.json"])
        self.assertIsNotNone(self.pane("home"))

    def test_hide(self):
        self.seed_token()
        self.make(hide=["person.alex"]).cycle()
        self.assertNotIn("Alex", self.pane("home", "pane.html"))


if __name__ == "__main__":
    unittest.main()
