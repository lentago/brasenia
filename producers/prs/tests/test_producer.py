import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta

from helpers import NOW, event

from prs_producer import producer
from prs_producer.github import GitHubError
from prs_producer.producer import Producer


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Snapshot:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, since, scope):
        self.calls.append((since, scope))
        if self.fail:
            raise GitHubError("search answered HTTP 403")
        return {"open": 3, "opened_today": 12, "merged_today": 9,
                "events": [event("lentago/kalmia", 276, "Start with Remote Control", "merged", 29)]}


class ProducerTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.pane = os.path.join(self.root, "viewport", "panes", "prs")
        self.clock, self.snap = Clock(), Snapshot()
        self.producer = Producer(self.root, snapshot=self.snap, clock=self.clock)

    def manifest(self):
        with open(os.path.join(self.pane, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def page(self):
        with open(os.path.join(self.pane, "pane.html"), encoding="utf-8") as fh:
            return fh.read()

    def test_writes_the_pane(self):
        self.producer.cycle()
        self.assertEqual(sorted(os.listdir(self.pane)), ["manifest.json", "pane.html"])
        m = self.manifest()
        self.assertEqual((m["schema"], m["class"], m["title"], m["ttl_minutes"], m["author"], m["origin"]),
                         (1, "ambient", "Pull requests", 10, "prs-producer@pub", "operator"))
        self.assertEqual(m["created"], "2026-11-02T23:40:00Z")
        self.assertIn("Start with Remote Control", self.page())

    def test_today_starts_at_local_midnight(self):
        self.producer.cycle()
        since, scope = self.snap.calls[0]
        self.assertEqual(since.isoformat(), "2026-11-02T00:00:00-05:00")
        self.assertEqual(scope, "org:lentago")

    def test_refresh_is_paced_but_the_pane_is_renewed(self):
        self.producer.cycle()
        self.clock.now = NOW + timedelta(seconds=producer.REFRESH_S - 1)
        self.producer.cycle()
        self.assertEqual(len(self.snap.calls), 1)
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:41:59Z")
        self.clock.now = NOW + timedelta(seconds=producer.REFRESH_S)
        self.producer.cycle()
        self.assertEqual(len(self.snap.calls), 2)

    def test_a_failed_refresh_keeps_the_last_list(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(minutes=5)
        self.producer.cycle()
        page = self.page()
        self.assertIn("Start with Remote Control", page)
        self.assertIn("GitHub unavailable, last tried 6:45 PM", page)
        self.assertIn("GitHub search · as of 6:40 PM", page)
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:45:00Z")

    def test_recovery_clears_the_warning(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(minutes=3)
        self.producer.cycle()
        self.snap.fail = False
        self.clock.now = NOW + timedelta(minutes=6)
        self.producer.cycle()
        self.assertNotIn("GitHub unavailable", self.page())

    def test_nothing_is_written_before_the_first_good_search(self):
        self.snap.fail = True
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane))

    def test_stale_data_is_left_to_its_ttl(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(seconds=producer.STALE_S + 60)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:40:00Z")

    def test_someone_elses_pane_is_left_alone(self):
        os.makedirs(self.pane)
        with open(os.path.join(self.pane, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"author": "someone@else"}, fh)
        self.producer.cycle()
        self.assertEqual(self.manifest(), {"author": "someone@else"})
        self.assertFalse(os.path.exists(os.path.join(self.pane, "pane.html")))


if __name__ == "__main__":
    unittest.main()
