import re
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from helpers import fixture
from family_brief_producer.render import FLOOR, ROW_W, _lines, render

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
        self.assertGreaterEqual(min(sizes), FLOOR)
        # The main area ends at 969 px, above the clock corner, and the
        # header, columns, strip and two gaps fill it.
        self.assertIn("top: 36px; left: 36px; right: 36px; height: 933px;", page)
        cols = float(re.search(r"\.cols \{[^}]*height: ([\d.]+)px", page).group(1))
        strip = float(re.search(r"\.decide \{[^}]*height: ([\d.]+)px", page).group(1))
        self.assertAlmostEqual(90 + 18 + cols + 18 + strip, 933, places=1)
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
        self.assertIn("No brief yet today: showing Sunday&#x27;s", page)
        self.assertNotIn("Coverage", today)
        # Seven items fit by bringing the type down; none is cut.
        self.assertEqual(tomorrow.count('class="row'), 7)
        self.assertNotIn("more on the board", tomorrow)
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


def body_size(page):
    return float(re.search(r"body \{[^}]*font-size: ([\d.]+)px", page, re.S).group(1))


class FitTests(unittest.TestCase):
    """Text wraps instead of being cut, and the type fills the band."""

    def test_nothing_is_cut_with_an_ellipsis(self):
        page = render(fixture(), SUN, NOW, TZ)
        self.assertNotIn("text-overflow", page)
        self.assertNotIn("line-clamp", page)

    def test_a_quiet_day_gets_bigger_type_than_a_busy_one(self):
        quiet = body_size(render(fixture(), SUN, NOW, TZ))
        busy = body_size(render(fixture(), MON, NOW, TZ))
        self.assertGreater(quiet, 33)
        self.assertGreaterEqual(busy, FLOOR)
        self.assertGreater(quiet, busy)

    def test_a_day_too_full_for_the_floor_ends_in_more(self):
        doc = fixture()
        items = doc["this_week"][0]["items"]
        doc["this_week"][0]["items"] = [dict(items[i % len(items)],
                                              what="Item %d with a long description that wraps" % i)
                                         for i in range(40)]
        page = render(doc, SUN, NOW, TZ)
        tomorrow = columns(page)[1]
        self.assertEqual(body_size(page), FLOOR)
        shown = tomorrow.count('class="row')
        more = int(re.search(r"\+(\d+) more on the board", tomorrow).group(1))
        self.assertGreater(shown, 0)
        self.assertEqual(shown + more, 40)

    def test_wrapping_estimate(self):
        self.assertEqual(_lines([("Cafe", False)], 33, ROW_W), 1)
        # Each word is about 100 px at 33 px, so a 250 px line holds two.
        self.assertEqual(_lines([("Appointment " * 4, False)], 33, 250), 4)
        # A word wider than the line breaks anywhere (and errs toward a line too many).
        self.assertIn(_lines([("abcdefghij" * 10, False)], 33, 300), (6, 7))
        # Bold runs count wider than regular ones.
        self.assertGreaterEqual(_lines([("Wednesday " * 8, True)], 33, 400),
                                _lines([("Wednesday " * 8, False)], 33, 400))
