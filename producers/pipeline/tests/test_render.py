import copy
import re
import unittest
from datetime import datetime, timezone

from helpers import fixture
from pipeline_producer.document import in_flight
from pipeline_producer.render import MAX_STRIPS, frontier, render, restamp

NOW = datetime(2026, 10, 7, 22, 11, tzinfo=timezone.utc)
AS_OF = datetime(2026, 10, 7, 22, 10, tzinfo=timezone.utc)

# bin/pane's EXTERNAL patterns: what `pane claim` refuses.
EXTERNAL = (
    re.compile(r"<script\b[^>]*?\bsrc\s*=[^>]*", re.I),
    re.compile(r"<link\b[^>]*?\bhref\s*=[^>]*", re.I),
    re.compile(r"\bsrc\s*=\s*[\"']?https?:[^\s>]*", re.I),
)


def flying():
    return in_flight(fixture("in-flight")["repos"])


def strips(page):
    return re.findall(r'<div class="strip[^"]*">.*?</div>\n</div>', page, re.S)


class RenderTests(unittest.TestCase):
    def test_pane_contract(self):
        page = render(flying(), AS_OF, NOW)
        for pattern in EXTERNAL:
            self.assertIsNone(pattern.search(page), pattern.pattern)
        self.assertNotIn("<script", page)
        self.assertIn("width: 1280px; height: 720px;", page)
        sizes = [int(px) for px in re.findall(r"font-size: (\d+)px", page)]
        self.assertGreaterEqual(min(sizes), 20)
        # Fixed layout: header + four strips fit the 622 px main area, which
        # ends at 646 px, above the clock corner; the footer stops short of it.
        self.assertIn("top: 24px; left: 24px; right: 24px; height: 622px;", page)
        self.assertLessEqual(64 + MAX_STRIPS * (130 + 8), 622)
        self.assertIn("left: 24px; bottom: 24px; width: 900px;", page)
        self.assertLessEqual(24 + 900, 1280 - 220 - 24)

    def test_strip_content(self):
        page = render(flying(), AS_OF, NOW)
        drosera, kalmia = strips(page)
        self.assertIn('class="strip stuck"', drosera)
        self.assertIn("<b>drosera</b> · head 9f1c2ab · in flight 9 min", drosera)
        self.assertIn("stuck 9 min", drosera)
        self.assertEqual(re.findall(r'class="stage">([^<]+)<', drosera),
                         ["pushed", "PR open", "checks", "merged", "applied", "live"])
        self.assertEqual(re.findall(r'class="box s(\d)"', drosera), ["3", "0", "3", "3", "3", "1"])
        self.assertIn('<div class="sha">36398c0</div><div>alloy-lxc105 · lagging</div>', drosera)
        self.assertIn('class="strip"', kalmia)
        self.assertNotIn("stuck", kalmia)
        self.assertIn("terraform apply · in progress", kalmia)
        self.assertNotIn("brasenia", page)  # landed repos are not shown
        self.assertIn("<h1>2 changes in flight</h1>", page)
        self.assertIn("data as of", page)

    def test_marker_on_edge_into_frontier(self):
        drosera, kalmia = strips(render(flying(), AS_OF, NOW))
        # Five edges per strip; drosera is travelling into live (the 5th), kalmia into applied (the 4th).
        self.assertEqual(re.findall(r'<svg class="edge( go)?"', drosera), ["", "", "", "", " go"])
        self.assertEqual(re.findall(r'<svg class="edge( go)?"', kalmia), ["", "", "", " go", ""])
        page = render(flying(), AS_OF, NOW)
        self.assertIn("stroke-dashoffset", page)
        self.assertIn("@keyframes travel", page)

    def test_frontier(self):
        self.assertEqual(frontier([3, 0, 3, 3, 3, 1]), 5)
        self.assertEqual(frontier([3, 0, 3, 3, 2, 1]), 4)  # a failed apply stops it there
        self.assertEqual(frontier([3, 3, 3, 3, 3, 3]), None)
        self.assertEqual(frontier([0, 0, 0, 0, 0, 0]), None)

    def test_more_than_four_shows_the_four_oldest(self):
        base = flying()[1]
        repos = []
        for i in range(6):
            row = copy.deepcopy(base)
            row["repo"] = "lentago/r%d" % i
            row["in_flight_since"] = "2026-10-07T22:0%d:00Z" % (9 - i)
            repos.append(row)
        page = render(in_flight(repos), AS_OF, NOW)
        names = re.findall(r'<div class="head"><b>([^<]+)</b>', page)
        self.assertEqual(names, ["r5", "r4", "r3", "r2"])
        self.assertIn('<span class="more">+2 more</span>', page)
        self.assertIn("<h1>6 changes in flight</h1>", page)

    def test_escapes_document_text(self):
        row = copy.deepcopy(flying()[0])
        row["stages"][0]["detail"] = '<img src="http://x/y.png">'
        page = render([row], AS_OF, NOW)
        self.assertNotIn("<img", page)
        self.assertIn("1 change in flight", page)

    def test_restamp_keeps_strips(self):
        page = render(flying(), AS_OF, NOW)
        again = restamp(page, NOW)
        self.assertIn("no fresh pipeline data, last tried", again)
        self.assertEqual(strips(again), strips(page))
        self.assertEqual(restamp(again, NOW).count("no fresh pipeline data"), 1)
        self.assertIsNone(restamp("<html></html>", NOW))


if __name__ == "__main__":
    unittest.main()
