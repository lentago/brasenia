import copy
import re
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from helpers import fixture
from family_brief_producer.detail import (DECISIONS, TODAY_ROWS, TODAY_ROWS_UNDER_COVERAGE,
                                          TODOS, TOMORROW_ROWS, render_detail)
from test_render import EXTERNAL

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
SUN, MON = date(2026, 10, 25), date(2026, 10, 26)


def section(page, cls):
    return re.search(r'<section class="col %s">.*?</section>' % cls, page, re.S).group(0)


class DetailTests(unittest.TestCase):
    def test_page_contract(self):
        page = render_detail(fixture(), SUN, NOW, TZ)
        for pattern in EXTERNAL:
            self.assertIsNone(pattern.search(page), pattern.pattern)
        self.assertNotIn("<script", page)
        self.assertIn("width: 1920px; height: 1080px;", page)
        sizes = [int(px) for px in re.findall(r"font-size: (\d+)px", page)]
        self.assertGreaterEqual(min(sizes), 18)
        # The main area (header + gap + columns) ends at 969 px, above the clock corner.
        self.assertIn("top: 36px; left: 36px; right: 36px; height: 933px;", page)
        self.assertEqual(36 + 64 + 14 + 855, 969)
        self.assertEqual(480 + 14 + 361, 855)
        self.assertEqual(472 + 14 + 369, 855)
        # Each list's slots fit its panel: padding, heading, slots (and the callout).
        head = 28 + 36 + 8
        self.assertLessEqual(head + TODAY_ROWS * 56, 480)
        self.assertLessEqual(head + TODAY_ROWS_UNDER_COVERAGE * 56 + 8 + 87, 480)
        self.assertLessEqual(head + TOMORROW_ROWS * 56, 361)
        self.assertLessEqual(head + DECISIONS * 80, 472)
        self.assertLessEqual(head + TODOS * 56, 369)
        # The footer stops short of the clock corner.
        self.assertIn("left: 36px; bottom: 30px; width: 1400px;", page)
        self.assertLessEqual(36 + 1400, 1920 - 330 - 36)
        # It zooms to fill the office shooter's 1280x720 viewport and a 4K one.
        self.assertIn("zoom: 0.666667", page)
        self.assertIn("zoom: 2", page)

    def test_brief_day(self):
        page = render_detail(fixture(), SUN, NOW, TZ)
        self.assertIn("<h1>Sunday, October 25</h1>", page)
        self.assertIn("Morning edition, 7:09 AM Eastern", page)
        today, tomorrow = section(page, "today"), section(page, "tomorrow")
        self.assertIn("Today <span>Sun 10/25</span>", today)
        self.assertIn("<b>Coverage:</b> No kid handoffs today.", today)
        self.assertIn("Tomorrow <span>Mon 10/26</span>", tomorrow)
        self.assertEqual(tomorrow.count('class="row'), 5)

    def test_every_decision_with_detail_in_date_order(self):
        page = render_detail(fixture(), SUN, NOW, TZ)
        decisions = section(page, "decisions")
        self.assertIn("Needs a decision <span>3</span>", decisions)
        self.assertEqual(decisions.count('class="decision'), 3)
        self.assertNotIn("more on the board", decisions)
        titles = re.findall(r"<b>(.*?)</b>", decisions)
        self.assertEqual(titles, ["Who does pickups Mon 10/26?",
                                  "Which time is Alex&#x27;s Tue 10/27 appointment?",
                                  "Trip Nov 24 - 27 overlaps piano"])
        self.assertIn('<div class="detail">Both clubs end while Jordan is at tennis.</div>', decisions)
        # Tomorrow's decision is flagged; a later one carries its date, unflagged.
        self.assertIn('<div class="decision near"><div class="dtitle"><b>Who does pickups Mon 10/26?</b>'
                      '<span class="when">Tomorrow</span>', decisions)
        self.assertIn('<div class="decision"><div class="dtitle"><b>Trip Nov 24 - 27 overlaps piano</b>'
                      '<span class="when">Tue 11/24</span>', decisions)

    def test_too_many_decisions_end_in_more(self):
        doc = copy.deepcopy(fixture())
        doc["decisions"] = [{"title": "D%d" % i, "dates": ["2026-11-%02d" % (i + 1)]} for i in range(8)]
        decisions = section(render_detail(doc, SUN, NOW, TZ), "decisions")
        self.assertEqual(decisions.count('class="decision'), DECISIONS - 1)
        self.assertIn("+%d more on the board" % (8 - (DECISIONS - 1)), decisions)

    def test_todos_by_due_date_with_deadlines(self):
        doc = copy.deepcopy(fixture())
        doc["todos"] = [
            {"tag": "BUY", "text": "Plates", "deadline": "Due Fri 10/30", "due": "2026-10-30"},
            {"tag": "SIGN", "text": "Field trip form", "due": "2026-10-26"},
            {"tag": "OPTIONAL", "text": "Clothing swap", "deadline": "Drop-off ends this morning",
             "due": "2026-10-25"},
            {"text": "Someday"},
        ]
        todos = section(render_detail(doc, SUN, NOW, TZ), "todos")
        self.assertIn("To do <span>4</span>", todos)
        texts = re.findall(r'<div class="ttext">(.*?)</div>', todos)
        self.assertEqual(texts, ["Clothing swap", "Field trip form", "Plates", "Someday"])
        # Due today or tomorrow is flagged; a missing deadline falls back to the due date.
        self.assertIn('<div class="todo near"><div class="ttag">OPTIONAL</div>', todos)
        self.assertIn('<div class="due">Due Mon 10/26</div>', todos)
        self.assertIn('<div class="todo"><div class="ttag">BUY</div>', todos)

    def test_day_after_brief_drops_status_and_coverage(self):
        page = render_detail(fixture(), MON, NOW, TZ)
        self.assertIn("No brief yet today: showing Sunday&#39;s", page)
        self.assertIn('<div class="status"></div>', page)
        self.assertNotIn("Coverage:", page)

    def test_empty_sections(self):
        doc = copy.deepcopy(fixture())
        doc["decisions"], doc["todos"] = [], None
        page = render_detail(doc, SUN, NOW, TZ)
        self.assertIn("No open decisions.", page)
        self.assertIn("Nothing to do.", page)
