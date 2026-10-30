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
        self.assertIn("width: 1920px; height: 1080px;", page)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', page)
        self.assertNotIn("zoom", page)
        sizes = [float(px) for px in re.findall(r"font-size: ([\d.]+)px", page)]
        self.assertGreaterEqual(min(sizes), 30)
        # Fixed layout: header + gap + columns + gap + strip fill the 933 px main
        # area, which ends at 969 px, above the clock corner.
        self.assertIn("top: 36px; left: 36px; right: 36px; height: 933px;", page)
        self.assertEqual(90 + 18 + 678 + 18 + 129, 933)
        # A column's slots fit inside it: padding, heading, rows (and the callout).
        self.assertLessEqual(42 + 51 + 12 + ROWS * 93, 678)
        self.assertLessEqual(42 + 51 + 12 + (ROWS - 1) * 93 + 12 + 96, 678)
        self.assertIn("left: 36px; bottom: 36px; width: 1350px;", page)
        self.assertLessEqual(36 + 1350, 1920 - 330 - 36)

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

    def test_where_follows_what_without_a_stray_full_stop(self):
        doc = fixture()
        item = doc["today"]["items"][0]
        item.update(what="Assembly, then the reading test. Families welcome.",
                    where="Harborlight", bring="a snack")
        today = columns(render(doc, SUN, NOW, TZ))[0]
        self.assertIn("Families welcome, Harborlight, bring a snack", today)
        self.assertNotIn(".,", today)
        # A full stop with nothing after it stays.
        item.update(where="", bring="")
        self.assertIn("Families welcome.</div>", columns(render(doc, SUN, NOW, TZ))[0])
        # No what: the place stands alone, with no leading comma.
        item.update(what="", where="Harborlight")
        self.assertIn('<div class="what"><span class="who">', columns(render(doc, SUN, NOW, TZ))[0])
        self.assertRegex(columns(render(doc, SUN, NOW, TZ))[0], r"</span> Harborlight</div>")

    def test_empty_day(self):
        doc = fixture()
        doc["today"] = {}
        page = render(doc, SUN, NOW, TZ)
        self.assertIn("Nothing on the calendar.", columns(page)[0])
