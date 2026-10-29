import re
import shutil
import tempfile
import unittest
from datetime import timedelta
from zoneinfo import ZoneInfo

from helpers import NOW, SECRET, Queue, pr

from fleet_producer import queue
from fleet_producer.render import render

TZ = ZoneInfo("America/New_York")


class RenderTest(unittest.TestCase):

    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        q = Queue(root)
        for host in ("claude-runner", "claude-runner-2", "claude-runner-3"):
            q.worker(host)
        q.worker("claude-runner-4", age_s=900)
        q.claim("20261029T002800Z-work-issue", "claude-runner-2", project="kalmia", started_ago_s=720)
        q.write("inbox/next.json", '{"prompt": "%s", "project": "drosera"}' % SECRET)
        q.run("one", 1, project="brasenia", model="opus", duration_s=300)
        q.run("two", 2, project="kalmia", exit_code=7, limit="timeout", duration_s=5400)
        self.snap = queue.snapshot(root, NOW)
        self.prs = {"total": 2, "items": [pr("lentago/brasenia", 87, "Fix the thing", 5),
                                          pr("cpitzi/music-curator", 12, "Tune the curator", 30, draft=True)],
                    "as_of": NOW, "error": None}

    def test_contract_and_no_prompt(self):
        page = render(self.snap, self.prs, NOW, TZ)
        self.assertNotRegex(page, r"(?i)<script|<link\b|\bsrc\s*=")
        self.assertIn("width: 1280px; height: 720px", page)
        self.assertNotIn(SECRET, page)
        self.assertIn("claude-jobs queue · as of 8:40 PM", page)

    def test_tiles(self):
        page = render(self.snap, self.prs, NOW, TZ)
        tiles = re.findall(r'<div class="n[^"]*">(\d+)</div><div class="l">([^<]+)</div>', page)
        self.assertEqual(tiles, [("3", "workers alive"), ("1", "busy"), ("1", "waiting"),
                                 ("2", "runs, 24 h"), ("1", "failed, 24 h")])

    def test_workers(self):
        page = render(self.snap, self.prs, NOW, TZ)
        self.assertIn('<span class="busy">kalmia</span> · 12 min', page)
        self.assertIn('<span class="bad">silent 15 min</span>', page)
        self.assertIn("waiting: drosera", page)

    def test_runs(self):
        page = render(self.snap, self.prs, NOW, TZ)
        self.assertIn("opus · 5 min · <span class=\"ok\">done</span>", page)
        self.assertIn("sonnet · 1 h 30 min · <span class=\"bad\">failed (timeout)</span>", page)

    def test_prs(self):
        page = render(self.snap, self.prs, NOW, TZ)
        self.assertIn("Agent PRs to review <span class=\"muted\">· 2</span>", page)
        self.assertIn("<b>brasenia</b> #87", page)
        self.assertIn("<b>music-curator</b> #12 <span class=\"muted\">· draft</span>", page)
        self.assertIn('<span class="right muted">30 h</span>', page)

    def test_more_prs_than_fit(self):
        items = [pr("lentago/kalmia", n, "PR %d" % n, 1) for n in range(1, 11)]
        page = render(self.snap, {"total": 12, "items": items, "as_of": NOW, "error": None}, NOW, TZ)
        self.assertIn("#5<", page)
        self.assertNotIn("#6<", page)
        self.assertIn("+7 more on GitHub", page)

    def test_stale_and_missing_pr_lists(self):
        stale = dict(self.prs, as_of=NOW - timedelta(minutes=20), error="search answered HTTP 403")
        self.assertIn("agent PRs as of 8:20 PM", render(self.snap, stale, NOW, TZ))
        never = {"total": 0, "items": [], "as_of": None, "error": "unreachable"}
        self.assertIn("GitHub search unavailable.", render(self.snap, never, NOW, TZ))
        self.assertIn("Nothing awaiting review.", render(self.snap, dict(self.prs, total=0, items=[]), NOW, TZ))

    def test_a_quiet_queue(self):
        empty = {"workers": [], "alive": 0, "busy": 0, "waiting": 0, "waiting_projects": [], "runs": []}
        page = render(empty, None, NOW, TZ)
        self.assertIn("No worker heartbeats.", page)
        self.assertIn("No runs in the last 24 hours.", page)


if __name__ == "__main__":
    unittest.main()
