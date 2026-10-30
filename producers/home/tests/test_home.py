import re
import unittest
from zoneinfo import ZoneInfo

from helpers import Clock, states

from home_producer import home

TZ = ZoneInfo("America/New_York")


def names(entries):
    return [e[0] for e in entries]


class Summarize(unittest.TestCase):

    def setUp(self):
        self.groups = home.summarize(states())

    def test_alarm_panels_and_their_states(self):
        self.assertEqual(self.groups["alarm"], [("Cameras", "Armed away", "ok"),
                                                ("House alarm", "Disarmed", "muted")])

    def test_people_skip_an_account_that_never_reports(self):
        self.assertEqual(self.groups["people"], [("Alex", "Home", "ok"), ("Robin", "Work", ""),
                                                 ("Sam", "Away", "muted")])

    def test_doors_and_windows_open_first_offline_last_no_shades_or_motion(self):
        self.assertEqual(names(self.groups["openings"]),
                         ["Back door", "Garage right", "Basement door", "Front door", "Garage left",
                          "Kitchen window", "Sliding door", "Attic hatch"])
        self.assertEqual(self.groups["openings"][0][1:], ("Open", "warn"))
        self.assertEqual(self.groups["openings"][-1][1:], ("Offline", "faint"))

    def test_locks_and_water(self):
        self.assertEqual(self.groups["locks"], [("Back door lock", "Unlocked", ""),
                                                ("Front door lock", "Locked", "muted")])
        self.assertEqual(self.groups["water"], [("Washer leak", "Dry", "muted"),
                                                ("Water heater leak", "Dry", "muted")])

    def test_climate(self):
        by = {c["name"]: c for c in self.groups["climate"]}
        self.assertEqual(by["Downstairs"], {"name": "Downstairs", "current": "69°", "set": "set 69°",
                                            "action": ("heating", "heat"), "humidity": "50% RH"})
        self.assertEqual(by["Upstairs"]["current"], "68°")       # 67.5 rounds half up
        self.assertEqual(by["Garage heater"]["action"], ("off", "faint"))
        self.assertEqual(by["Garage heater"]["set"], "")

    def test_hide(self):
        groups = home.summarize(states(), hide=["person.sam", "lock.back_door"])
        self.assertNotIn("Sam", names(groups["people"]))
        self.assertEqual(names(groups["locks"]), ["Front door lock"])

    def test_a_wet_sensor_and_a_triggered_alarm(self):
        doc = states()
        for s in doc:
            if s["entity_id"] == "binary_sensor.washer_leak":
                s["state"] = "on"
            if s["entity_id"] == "alarm_control_panel.house":
                s["state"] = "triggered"
        groups = home.summarize(doc)
        self.assertIn(("Washer leak", "Wet", "bad"), groups["water"])
        self.assertIn(("House alarm", "Triggered", "bad"), groups["alarm"])
        page = home.render_home(groups, Clock()(), TZ)
        self.assertIn('<span class="bad">Alarm triggered</span> · <span class="bad">1 wet</span>', page)


class Render(unittest.TestCase):

    def render(self, groups=None):
        return home.render_home(groups or home.summarize(states()), Clock()(), TZ)

    def test_contract(self):
        page = self.render()
        self.assertNotRegex(page, r"(?i)<script|<link\b|\bsrc\s*=")
        self.assertIn("width: 1920px; height: 1080px", page)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', page)
        self.assertNotIn("zoom", page)
        self.assertIn("Home Assistant · as of 8:40 PM", page)

    def test_header_summary(self):
        self.assertIn('<div class="summary">2 open · 1 of 3 home</div>', self.render())

    def test_every_entity_is_on_the_page(self):
        page = self.render()
        for name in ("Cameras", "Alex", "Robin", "Back door lock", "Downstairs", "Washer leak", "Attic hatch"):
            self.assertIn(name, page)
        for absent in ("Kiosk", "Living room shade", "Hall motion", "Outdoor temperature"):
            self.assertNotIn(absent, page)

    def test_a_long_list_ends_in_more_and_leaves_the_others_whole(self):
        groups = home.summarize(states())
        groups["openings"] = [("Door %02d" % i, "Closed", "muted") for i in range(30)]
        groups["locks"] = [("Lock %02d" % i, "Locked", "muted") for i in range(30)]
        page = self.render(groups)
        # the doors column holds (550 - 52) // 38 = 13 rows: 12 doors and "+18 more"
        self.assertIn("Door 11", page)
        self.assertNotIn("Door 12", page)
        self.assertIn('<div class="row more">+18 more</div>', page)
        # Alarm (2) and People (3) stay whole; Locks gets what is left of column a
        for name in ("Cameras", "House alarm", "Alex", "Robin", "Sam"):
            self.assertIn(name, page)
        rows = (550 - 3 * 52 - 2 * 12) // 38   # 9 rows for column a's cards
        self.assertEqual(len(re.findall(r">Lock \d\d<", page)), rows - 2 - 3 - 1)

    def test_an_empty_house(self):
        page = home.render_home(home.summarize([]), Clock()(), TZ)
        self.assertIn("Home Assistant lists nothing for this pane yet.", page)


if __name__ == "__main__":
    unittest.main()
