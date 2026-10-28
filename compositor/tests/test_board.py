import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from compositor import board, rubric  # noqa: E402
from compositor.rubric import decide  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
FRESH = {"present": True, "mtime": T0 - timedelta(hours=2)}
STALE = {"present": True, "mtime": T0 - timedelta(days=37)}
ABSENT = {"present": False, "mtime": None}


def pane(pane_id, cls="focus", ttl=10):
    return {"id": pane_id, "files": {"pane.html", "manifest.json"}, "manifest": {
        "schema": 1, "class": cls, "title": "%s title" % pane_id,
        "created": rubric.iso(T0), "ttl_minutes": ttl, "author": "t@u"}}


def page(panes, brief=FRESH, now=T0):
    pointer, _ = decide(panes, now, {}, brief_present=brief["present"])
    return board.render(pointer, rubric.explain(panes, now, pointer), brief, now)


def active_rung(text):
    return re.search(r'<li class="rung active">.*?<span class="cls">(.*?)</span>', text).group(1)


class Board(unittest.TestCase):

    def test_self_contained(self):
        text, _ = page([pane("a")])
        self.assertNotIn("<script", text)
        self.assertIsNone(re.search(r'(src|href)="https?://(?!pub\.lan)', text))
        self.assertIn('<meta http-equiv="refresh" content="10">', text)

    def test_a_live_pane_lights_its_rung(self):
        text, _ = page([pane("a", "attention"), pane("b", "ambient")])
        self.assertEqual(active_rung(text), "attention")
        self.assertIn('<span class="chip showing">a</span>', text)
        self.assertIn('<span class="chip outranked">b</span>', text)
        self.assertIn("a title", text)

    def test_every_class_has_a_rung_and_both_fallbacks_are_listed(self):
        text, _ = page([])
        for cls in rubric.PRIORITY:
            self.assertIn('<span class="cls">%s</span>' % cls, text)
        self.assertIn('<span class="cls">status card</span>', text)
        self.assertEqual(active_rung(text), "briefing")
        self.assertIn("The bus is empty", text)

    def test_a_stale_brief_is_flagged(self):
        text, _ = page([], brief=STALE)
        self.assertIn("(37 days ago): stale", text)
        text, _ = page([], brief=FRESH)
        self.assertNotIn("stale", text)

    def test_no_brief_points_at_the_status_card(self):
        text, _ = page([], brief=ABSENT)
        self.assertEqual(active_rung(text), "status card")
        self.assertIn("Fallback: the status card", text)
        self.assertIn("skipped: no briefing is published", text)

    def test_the_key_ignores_only_the_generated_clock(self):
        text, key = page([pane("a")])
        self.assertEqual(board.key_of(text), key)
        _, same = page([pane("a")], now=T0 + timedelta(seconds=2))
        self.assertEqual(same, key)
        _, other = page([pane("a"), pane("b", "alert")])
        self.assertNotEqual(other, key)

    def test_escapes_titles(self):
        p = pane("a")
        p["manifest"]["title"] = "<b>PRs & such</b>"
        text, _ = page([p])
        self.assertIn("&lt;b&gt;PRs &amp; such&lt;/b&gt;", text)
        self.assertNotIn("<b>PRs", text)


    def test_times_are_shown_in_the_given_zone(self):
        panes = [pane("a")]
        pointer, _ = decide(panes, T0, {}, brief_present=True)
        rows = rubric.explain(panes, T0, pointer)
        eastern, _ = board.render(pointer, rows, FRESH, T0, tz=ZoneInfo("America/New_York"))
        self.assertIn("Generated 8:00:00 AM EDT", eastern)
        self.assertIn("live until 8:10 AM (in 10 min)", eastern)
        utc, _ = board.render(pointer, rows, FRESH, T0, tz=timezone.utc)
        self.assertIn("Generated 12:00:00 PM UTC", utc)


if __name__ == "__main__":
    unittest.main()
