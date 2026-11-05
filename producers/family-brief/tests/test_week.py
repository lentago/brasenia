import copy
import re
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from helpers import fixture
from family_brief_producer.render import FLOOR
from family_brief_producer.week import DAYS, WEEK_H, render_week, week_days
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
        self.assertIn("width: 1920px; height: 1080px;", page)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', page)
        self.assertGreaterEqual(min(float(px) for px in re.findall(r"font-size: ([\d.]+)px", page)), FLOOR)
        self.assertEqual(90 + 18 + WEEK_H, 933)
        self.assertIn("<h1>This week <span>Sun 10/25 – Sat 10/31</span></h1>", page)
        r = rows(page)
        self.assertEqual(len(r), DAYS)
        self.assertIn('class="day today"', r[0])
        self.assertIn("<b>Today</b> <span class=\"md\">10/25</span>", r[0])
        self.assertIn('class="day flagged"', r[1])
        self.assertIn('<span class="chip">coverage gap</span>', r[1])
        self.assertIn('<span class="chip">crunch day</span>', r[2])
        self.assertIn('<span class="chip quiet">1 due</span>', r[2])
        self.assertIn("Nothing on the calendar.", r[6])
        self.assertNotIn("zoom", page)

    def test_a_stale_brief_says_so(self):
        page = render_week(doc_with_week(), date(2026, 10, 28), NOW, TZ)
        self.assertIn("No brief since Sun 10/25", page)


def body_size(page):
    return float(re.search(r"body \{ width[^}]*font-size: ([\d.]+)px", page).group(1))


class WeekFitTests(unittest.TestCase):
    def test_the_header_shows_the_edition_text(self):
        page = render_week(doc_with_week(), SUN, NOW, TZ)
        self.assertIn('<div class="edition">Morning edition, 7:09 AM Eastern</div></header>', page)
        stale = render_week(doc_with_week(), date(2026, 10, 28), NOW, TZ)
        self.assertIn('<div class="edition stale">No brief since Sun 10/25</div>', stale)

    def test_nothing_is_cut_with_an_ellipsis(self):
        page = render_week(doc_with_week(), SUN, NOW, TZ)
        self.assertNotIn("text-overflow", page)
        self.assertNotIn("line-clamp", page)
        self.assertNotIn("more</span>", page)

    def test_a_light_week_gets_bigger_type_than_a_heavy_one(self):
        light = body_size(render_week(doc_with_week(), SUN, NOW, TZ))
        doc = doc_with_week()
        for w in doc["this_week"]:
            w["items"] = (w["items"] * 3)[:12]
        heavy = body_size(render_week(doc, SUN, NOW, TZ))
        self.assertGreater(light, 31.5)
        self.assertGreater(light, heavy)
        self.assertGreaterEqual(heavy, FLOOR)

    def test_a_week_too_full_for_the_floor_ends_days_in_more(self):
        doc = doc_with_week()
        for w in doc["this_week"]:
            w["items"] = [dict(w["items"][i % len(w["items"])],
                               what="Item %d with a long description that wraps around" % i)
                          for i in range(40)]
        page = render_week(doc, SUN, NOW, TZ)
        self.assertEqual(body_size(page), FLOOR)
        r = rows(page)
        for row in r[1:3]:
            shown = row.count('class="who"')
            more = int(re.search(r"\+(\d+) more</span>", row).group(1))
            self.assertEqual(shown + more, 40)
