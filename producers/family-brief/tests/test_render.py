import re
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from helpers import fixture
from family_brief_producer.render import ROWS, render

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
SUN, MON = date(2026, 10, 25), date(2026, 10, 26)

# bin/pane's EXTERNAL patterns: what `pane claim` refuses.
EXTERNAL = (
    re.compile(r"<script\b[^>]*?\bsrc\s*=[^>]*", re.I),
    re.compile(r"<link\b[^>]*?\bhref\s*=[^>]*", re.I),
    re.compile(r"\bsrc\s*=\s*[\"']?https?:[^\s>]*", re.I),
)


def columns(page):
    return re.findall(r'<section class="col">.*?</section>', page, re.S)


class RenderTests(unittest.TestCase):
    def test_pane_contract(self):
        page = render(fixture(), SUN, NOW, TZ)
        for pattern in EXTERNAL:
            self.assertIsNone(pattern.search(page), pattern.pattern)
        self.assertNotIn("<script", page)
        self.assertIn("width: 1280px; height: 720px;", page)
        sizes = [int(px) for px in re.findall(r"font-size: (\d+)px", page)]
        self.assertGreaterEqual(min(sizes), 20)
        # Fixed layout: header + gap + columns + gap + strip fill the 622 px main
        # area, which ends at 646 px, above the clock corner.
        self.assertIn("top: 24px; left: 24px; right: 24px; height: 622px;", page)
        self.assertEqual(60 + 12 + 452 + 12 + 86, 622)
        # A column's slots fit inside it: padding, heading, rows (and the callout).
        self.assertLessEqual(28 + 34 + 8 + ROWS * 62, 452)
        self.assertLessEqual(28 + 34 + 8 + (ROWS - 1) * 62 + 8 + 64, 452)
        self.assertIn("left: 24px; bottom: 24px; width: 900px;", page)
        self.assertLessEqual(24 + 900, 1280 - 220 - 24)
        self.assertIn("zoom: 1.5", page)

    def test_brief_day(self):
        page = render(fixture(), SUN, NOW, TZ)
        today, tomorrow = columns(page)
        self.assertIn("<h1>Sunday, October 25</h1>", page)
        self.assertIn("Morning edition, 7:09 AM Eastern", page)
        self.assertIn("Today <span>Sun 10/25</span>", today)
        self.assertIn("Brunch with a friend, the diner", today)
        self.assertIn("<b>Coverage:</b> No kid handoffs today.", today)
        self.assertIn("Tomorrow <span>Mon 10/26</span>", tomorrow)
        self.assertEqual(tomorrow.count('class="row'), 5)
        self.assertNotIn("more on the board", tomorrow)
        self.assertIn("<li>Who does pickups Mon 10/26?</li>", page)
        self.assertNotIn("Trip Nov 24", page)
        self.assertIn("2 more on the board", page)

    def test_person_colours_come_from_the_legend(self):
        page = render(fixture(), SUN, NOW, TZ)
        self.assertIn('style="--pc: #f06292"><div class="time">10:30 - 11:30 AM', page)

    def test_day_after_overflows_into_more(self):
        page = render(fixture(), MON, NOW, TZ)
        today, tomorrow = columns(page)
        self.assertIn("No brief yet today: showing Sunday&#39;s", page)
        self.assertNotIn("Coverage", today)
        self.assertEqual(tomorrow.count('class="row'), ROWS - 1)
        self.assertIn("+2 more on the board", tomorrow)
        self.assertIn('class="row cancelled"', tomorrow)
        self.assertIn('<span class="unconf">▲</span>', tomorrow)
        self.assertIn('<span class="tag">Legacy</span>', tomorrow)

    def test_text_is_escaped(self):
        doc = fixture()
        doc["today"]["items"][0]["what"] = "<img src=x onerror=alert(1)>"
        page = render(doc, SUN, NOW, TZ)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x", page)

    def test_malformed_people_counts_as_none(self):
        doc = fixture()
        doc["today"]["items"][0]["people"] = 42
        doc["this_week"][0]["items"][0]["people"] = "notalist"
        page = render(doc, SUN, NOW, TZ)
        self.assertEqual(len(columns(page)), 2)

    def test_empty_day(self):
        doc = fixture()
        doc["today"] = {}
        page = render(doc, SUN, NOW, TZ)
        self.assertIn("Nothing on the calendar.", columns(page)[0])
