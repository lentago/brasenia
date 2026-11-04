import re
import unittest
from datetime import timedelta
from zoneinfo import ZoneInfo

from helpers import NOW, event

from prs_producer.render import render, waits_on

TZ = ZoneInfo("America/New_York")
OK = {"as_of": NOW, "error": None, "tried": NOW, "token": True, "paused": False, "states": {}}


def data(events):
    return {"open": 23, "opened_today": 92, "merged_today": 69, "events": events}


class RenderTest(unittest.TestCase):

    def setUp(self):
        self.events = [
            event("lentago/kalmia", 276, "Start sessions with Remote Control", "merged", 29, who="bullpen"),
            event("lentago/claytonia", 197, "Rebuild claude-runner-4", "open", 99),
            event("lentago/shared-workflows", 101, "Bump <the> group & co", "draft", 0, who="dependabot"),
            event("lentago/betula", 150, "Superseded bump", "closed", 60 * 26),
            event("lentago/drosera", 300, "An old one", "merged", 60 * 24 * 9),
        ]

    def test_contract(self):
        page = render(data(self.events), OK, "org:lentago", NOW, TZ)
        self.assertNotRegex(page, r"(?i)<script|<link\b|\bsrc\s*=")
        self.assertIn("width: 1920px; height: 1080px", page)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', page)
        sizes = [float(s) for s in re.findall(r"font-size: ([\d.]+)px", page)]
        self.assertTrue(sizes and min(sizes) >= 30, sizes)
        # The main area ends at y=969 and the footer at x=1386: clear of the 330×75 clock corner.
        self.assertIn("top: 36px; left: 36px; right: 36px; height: 933px", page)
        self.assertIn("left: 36px; bottom: 36px; width: 1350px", page)

    def test_header_and_counts(self):
        page = render(data(self.events), OK, "org:lentago", NOW, TZ)
        self.assertIn("<h1>Pull requests <span>lentago</span></h1>", page)
        tiles = re.findall(r'<div class="n[^"]*">(\d+)</div><div class="l">([^<]+)</div>', page)
        self.assertEqual(tiles, [("23", "open now"), ("92", "opened today"), ("69", "merged today")])
        self.assertIn('<div class="foot">GitHub search · as of 6:40 PM</div>', page)
        self.assertIn('<div class="summary"></div>', page)

    def test_rows(self):
        page = render(data(self.events), OK, "org:lentago", NOW, TZ)
        rows = re.findall(r'<span class="chip"[^>]*>(\w+)</span><span class="repo">([^<]+)</span>'
                          r'<span class="num">#(\d+)</span><span class="title">([^<]+)</span>'
                          r'<span class="who">([^<]+)</span><span class="when">([^<]+)</span>', page)
        self.assertEqual(rows, [
            ("merged", "kalmia", "276", "Start sessions with Remote Control", "bullpen", "29 min"),
            ("open", "claytonia", "197", "Rebuild claude-runner-4", "cpitzi", "5:01 PM"),
            ("draft", "shared-workflows", "101", "Bump &lt;the&gt; group &amp; co", "dependabot", "now"),
            ("closed", "betula", "150", "Superseded bump", "cpitzi", "Sun"),
            ("merged", "drosera", "300", "An old one", "cpitzi", "Oct 24"),
        ])

    def test_ten_rows_at_most(self):
        many = [event("lentago/kalmia", n, "PR %d" % n, "merged", n) for n in range(1, 15)]
        page = render(data(many), OK, "org:lentago", NOW, TZ)
        self.assertEqual(page.count('<div class="row">'), 10)
        self.assertIn(">#10<", page)
        self.assertNotIn(">#11<", page)

    def test_github_unavailable(self):
        status = dict(OK, as_of=NOW - timedelta(minutes=6), error="search answered HTTP 403")
        page = render(data(self.events), status, "org:lentago", NOW, TZ)
        self.assertIn('<div class="summary">GitHub unavailable, last tried 6:40 PM</div>', page)
        self.assertIn("GitHub search · as of 6:34 PM", page)

    def test_open_rows_show_their_state_in_place_of_the_author(self):
        states = {
            "PR_claytonia_197": {"checks": "failing", "armed": True, "reviewed": True},
            "PR_shared-workflows_101": {"checks": "failing", "armed": False, "reviewed": False},
            "PR_kalmia_276": {"checks": "passing", "armed": True, "reviewed": True},
        }
        page = render(data(self.events), dict(OK, states=states), "org:lentago", NOW, TZ)
        whos = re.findall(r'<span class="(who[^"]*)"(?: style="color: (#\w+)")?>([^<]+)</span>', page)
        self.assertEqual(whos, [
            ("who", "", "bullpen"),                       # merged: the author, whatever the state
            ("who state", "#f85149", "checks failing"),   # open
            ("who", "", "dependabot"),                    # draft: the author
            ("who", "", "cpitzi"),
            ("who", "", "cpitzi"),
        ])

    def test_an_open_row_without_a_known_state_shows_its_author(self):
        page = render(data(self.events), dict(OK, states={"PR_other_1": {}}), "org:lentago", NOW, TZ)
        self.assertNotIn("who state", page)
        self.assertIn('<span class="who">cpitzi</span>', page)

    def test_waits_on(self):
        def word(checks, armed, reviewed):
            return waits_on({"checks": checks, "armed": armed, "reviewed": reviewed})

        self.assertEqual(word("failing", True, True), ("checks failing", "#f85149"))
        self.assertEqual(word("pending", True, False), ("armed", "#3fb950"))
        self.assertEqual(word("passing", False, False), ("awaiting review", "#f0a53a"))
        self.assertEqual(word("pending", False, True), ("checks running", "#58a6ff"))
        self.assertEqual(word("passing", False, True), ("reviewed", "#e4ebee"))
        self.assertEqual(word(None, False, True), ("reviewed", "#e4ebee"))

    def test_the_footer_says_when_there_is_no_token_or_state_is_paused(self):
        page = render(data(self.events), dict(OK, token=False), "org:lentago", NOW, TZ)
        self.assertIn('<div class="foot">GitHub search · as of 6:40 PM · no GitHub token</div>', page)
        page = render(data(self.events), dict(OK, paused=True), "org:lentago", NOW, TZ)
        self.assertIn('<div class="foot">GitHub search · as of 6:40 PM · PR state paused, rate limit low</div>',
                      page)

    def test_no_events_and_other_scopes(self):
        page = render(data([]), OK, "user:cpitzi", NOW, TZ)
        self.assertIn("No pull requests yet.", page)
        self.assertIn("<span>user:cpitzi</span>", page)


if __name__ == "__main__":
    unittest.main()
