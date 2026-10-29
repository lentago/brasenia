import re
import unittest
from zoneinfo import ZoneInfo

from helpers import Clock, forecast, states

from home_producer import weather

TZ = ZoneInfo("America/New_York")


def entity(**attrs):
    w = weather.pick(states())
    w["attributes"].update(attrs)
    return w


class Pick(unittest.TestCase):

    def test_the_first_weather_entity_by_id(self):
        doc = states() + [{"entity_id": "weather.a_station", "state": "sunny", "attributes": {}}]
        self.assertEqual(weather.pick(doc)["entity_id"], "weather.a_station")

    def test_a_named_entity(self):
        self.assertEqual(weather.pick(states(), "weather.home")["entity_id"], "weather.home")
        self.assertIsNone(weather.pick(states(), "weather.elsewhere"))
        self.assertIsNone(weather.pick([]))


class Render(unittest.TestCase):

    def render(self, hourly="fixture", daily="fixture", **attrs):
        return weather.render_weather(entity(**attrs),
                                      forecast("hourly") if hourly == "fixture" else hourly,
                                      forecast("daily") if daily == "fixture" else daily,
                                      Clock()(), TZ)

    def test_contract(self):
        page = self.render()
        self.assertNotRegex(page, r"(?i)<script|<link\b|\bsrc\s*=")
        self.assertIn("width: 1280px; height: 720px", page)
        self.assertIn("Weather forecast from met.no · as of 8:40 PM", page)
        self.assertIn('<div class="summary">Wednesday, October 28</div>', page)

    def test_now(self):
        page = self.render()
        self.assertIn('<div class="big">44°</div>', page)
        self.assertIn("High 45° · Low 44°", page)
        self.assertIn("<span>Wind</span><span>7 mph from S</span>", page)
        self.assertIn("<span>Pressure</span><span>30.39 inHg</span>", page)
        self.assertIn("Partly cloudy", page)

    def test_next_hours_every_three_hours_from_the_coming_hour(self):
        page = self.render()
        times = re.findall(r'<div class="t">([^<]+)</div>', page)
        self.assertEqual(times, ["9 PM", "12 AM", "3 AM", "6 AM", "9 AM", "12 PM", "3 PM", "6 PM"])
        self.assertIn('<div class="p">0.08 in</div>', page)
        self.assertEqual(page.count("<rect "), 3)      # three wet hours
        self.assertEqual(page.count("<circle "), 8)    # one point per column

    def test_past_hours_are_dropped(self):
        later = Clock("2026-10-29T03:30:00Z")()        # 11:30 PM; the 9 PM and 10 PM entries are past
        page = weather.render_weather(entity(), forecast("hourly"), forecast("daily"), later, TZ)
        self.assertEqual(re.findall(r'<div class="t">([^<]+)</div>', page)[0], "11 PM")

    def test_coming_days(self):
        page = self.render()
        self.assertEqual(re.findall(r'<div class="day">([^<]+)</div>', page),
                         ["Today", "Thu", "Fri", "Sat", "Sun", "Mon"])
        self.assertIn('<div class="hi">51°</div><div class="lo">41°</div><div class="p">0.42 in</div>', page)
        self.assertIn("Sleet", page)

    def test_without_forecasts(self):
        page = self.render(hourly=None, daily=None)
        self.assertIn("No hourly forecast.", page)
        self.assertIn("No daily forecast.", page)
        self.assertNotIn("High ", page)

    def test_metric_units(self):
        page = self.render(pressure=1013.2, pressure_unit="hPa", wind_speed=12.4, wind_speed_unit="km/h",
                           wind_bearing=350)
        self.assertIn("<span>Pressure</span><span>1013 hPa</span>", page)
        self.assertIn("<span>Wind</span><span>12 km/h from N</span>", page)


if __name__ == "__main__":
    unittest.main()
