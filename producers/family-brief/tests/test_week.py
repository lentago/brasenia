import copy
import re
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from helpers import fixture
from family_brief_producer.week import DAYS, render_week, render_week_detail, week_days
from test_render import EXTERNAL

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
SUN = date(2026, 10, 25)


def doc_with_week():
    doc = copy.deepcopy(fixture())
    doc["week"] = [{"date": "2026-10-25", "flag": "none", "alert": False},
                   {"date": "2026-10-26", "flag": "gap", "alert": True},
                   {"date": "2026-10-27", "flag": "crunch", "alert": True}]
    doc["todos"] = [{"tag": "BUY", "text": "Plates", "due": "2026-10-27"}]
    return doc


def rows(page):
    return re.findall(r'<div class="day[^"]*">.*?</div></div>', page, re.S)


class WeekTests(unittest.TestCase):
    def test_seven_days_from_today_with_the_right_items(self):
        days = week_days(doc_with_week(), SUN)
        self.assertEqual(len(days), DAYS)
        self.assertEqual([d[0] for d in days][:3], [SUN, date(2026, 10, 26), date(2026, 10, 27)])
        # The brief's own day comes from its today block; the next from this_week.
        self.assertIn("Brunch with a friend", [i.get("what") for i in days[0][1]])
        self.assertEqual(len(days[1][1]), 5)
        self.assertEqual([d[2] for d in days[:3]], [None, "gap", "crunch"])
        # Decisions touching Mon 10/26 and Tue 10/27; one to-do due Tue.
        self.assertEqual((days[1][3], days[2][3], days[2][4]), (1, 1, 1))
        self.assertEqual(days[6][1], [])

    def test_wall_cut_contract_and_content(self):
        page = render_week(doc_with_week(), SUN, NOW, TZ)
        for pattern in EXTERNAL:
            self.assertIsNone(pattern.search(page), pattern.pattern)
        self.assertNotIn("<script", page)
        self.assertIn("width: 1280px; height: 720px;", page)
        self.assertGreaterEqual(min(int(px) for px in re.findall(r"font-size: (\d+)px", page)), 20)
        self.assertLessEqual(60 + 12 + DAYS * 78, 622)
        self.assertIn("<h1>This week <span>Sun 10/25 – Sat 10/31</span></h1>", page)
        r = rows(page)
        self.assertEqual(len(r), DAYS)
        self.assertIn('class="day today"', r[0])
        self.assertIn("<b>Today</b>", r[0])
        self.assertIn('class="day flagged"', r[1])
        self.assertIn('<span class="chip">coverage gap</span>', r[1])
        self.assertIn('<span class="chip">crunch day</span>', r[2])
        self.assertIn('<span class="chip quiet">1 due</span>', r[2])
        self.assertIn("Nothing on the calendar.", r[6])
        self.assertIn("zoom: 1.5", page)

    def test_desk_edition_contract(self):
        page = render_week_detail(doc_with_week(), SUN, NOW, TZ)
        for pattern in EXTERNAL:
            self.assertIsNone(pattern.search(page), pattern.pattern)
        self.assertIn("width: 1920px; height: 1080px;", page)
        self.assertGreaterEqual(min(int(px) for px in re.findall(r"font-size: (\d+)px", page)), 18)
        self.assertLessEqual(36 + 64 + 14 + DAYS * 120, 1080 - 75)
        self.assertIn("zoom: 0.666667", page)
        self.assertEqual(len(rows(page)), DAYS)
        self.assertIn("<b>Monday</b>", page)

    def test_a_busy_day_ends_in_more(self):
        doc = doc_with_week()
        doc["this_week"][0]["items"] = [{"time": "9:00 AM", "who": "Jordan", "what": "x%d" % i}
                                        for i in range(9)]
        page = render_week_detail(doc, SUN, NOW, TZ)
        self.assertIn("+4 more on the board", page)

    def test_a_stale_brief_says_so(self):
        page = render_week(doc_with_week(), date(2026, 10, 28), NOW, TZ)
        self.assertIn("No brief since Sun 10/25", page)
