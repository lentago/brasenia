import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from fakes import FakeTransport, serve_repo
from focus_producer.github import GitHub
from focus_producer.producer import Producer


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def epoch(self):
        return self.now.timestamp()

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class ProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.webroot = self.tmp.name
        self.focus = os.path.join(self.webroot, "viewport", "focus")
        self.panes = os.path.join(self.webroot, "viewport", "panes")
        os.makedirs(self.focus)
        self.clock = Clock()
        self.t = FakeTransport()
        serve_repo(self.t, "lentago/brasenia",
                   [{"number": 28, "title": "Focus producer", "checks": [("completed", "success")]}])
        serve_repo(self.t, "lentago/kalmia", [], main_conclusion="failure")
        self.gh = GitHub(self.t, self.clock.epoch)
        self.producer = Producer(self.webroot, "http://pub.lan/", self.gh, self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def beacon(self, name, repo="lentago/brasenia", origin="operator"):
        body = {"schema": 1, "host": "thinkpad", "session": name[-8:], "repo": repo,
                "cwd": "/x", "origin": origin,
                "ts": self.clock.now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        with open(os.path.join(self.focus, name + ".json"), "w") as fh:
            json.dump(body, fh)

    def pane(self, pane_id, name):
        return os.path.join(self.panes, pane_id, name)

    def read(self, pane_id, name):
        with open(self.pane(pane_id, name), encoding="utf-8") as fh:
            return fh.read()

    def test_beacon_produces_pane_and_manifest(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        manifest = json.loads(self.read("focus-lentago-brasenia", "manifest.json"))
        self.assertEqual(manifest, {
            "schema": 1, "class": "focus", "title": "brasenia — open pull requests",
            "created": "2026-10-07T12:00:00Z", "ttl_minutes": 10,
            "author": "focus-producer@pub", "origin": "operator", "repo": "lentago/brasenia",
        })
        page = self.read("focus-lentago-brasenia", "pane.html")
        self.assertIn("Focus producer", page)
        self.assertIn("success", page)
        self.assertEqual(sorted(os.listdir(os.path.join(self.panes, "focus-lentago-brasenia"))),
                         ["manifest.json", "pane.html"])  # no .partial left behind

    def test_manifest_written_last(self):
        self.beacon("thinkpad-19ca7047")
        order = []
        real_replace = os.replace

        def spy(src, dst):
            order.append(os.path.basename(dst))
            real_replace(src, dst)
        os.replace = spy
        try:
            self.producer.cycle()
        finally:
            os.replace = real_replace
        self.assertEqual(order, ["pane.html", "manifest.json"])

    def test_created_slides_while_beacons_stay_fresh(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        self.clock.advance(30)
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        manifest = json.loads(self.read("focus-lentago-brasenia", "manifest.json"))
        self.assertEqual(manifest["created"], "2026-10-07T12:00:30Z")

    def test_fleet_only_origin(self):
        self.beacon("worker-aaaaaaaa", origin="fleet")
        self.producer.cycle()
        self.assertEqual(json.loads(self.read("focus-lentago-brasenia", "manifest.json"))["origin"],
                         "fleet")

    def test_second_repo_gets_its_own_pane_without_touching_the_first(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        first_page = self.read("focus-lentago-brasenia", "pane.html")
        self.beacon("worker-bbbbbbbb", repo="lentago/kalmia", origin="fleet")
        self.clock.advance(10)  # inside brasenia's hold
        self.producer.cycle()
        self.assertIn("failure", self.read("focus-lentago-kalmia", "pane.html"))
        self.assertNotIn("Focus producer", self.read("focus-lentago-kalmia", "pane.html"))
        self.assertEqual(self.read("focus-lentago-brasenia", "pane.html"), first_page)

    def test_403_keeps_previous_pane_and_updates_stamp(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        before = self.read("focus-lentago-brasenia", "pane.html")
        self.clock.advance(300)  # past the repo's hold, so a refresh is attempted
        self.beacon("thinkpad-19ca7047")
        self.t.fail = 403
        self.producer.cycle()
        after = self.read("focus-lentago-brasenia", "pane.html")
        self.assertIn("Focus producer", after)
        self.assertNotEqual(before, after)
        self.assertIn("GitHub unavailable, last tried %s"
                      % self.clock.now.astimezone().strftime("%H:%M"), after)
        manifest = json.loads(self.read("focus-lentago-brasenia", "manifest.json"))
        self.assertEqual(manifest["created"], "2026-10-07T12:05:00Z")

    def test_failure_with_no_previous_pane_writes_nothing(self):
        self.beacon("thinkpad-19ca7047")
        self.t.fail = "network"
        self.producer.cycle()
        self.assertFalse(os.path.exists(os.path.join(self.panes, "focus-lentago-brasenia")))

    def test_beacon_gone_removes_pane(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        os.unlink(os.path.join(self.focus, "thinkpad-19ca7047.json"))
        self.producer.cycle()
        self.assertFalse(os.path.exists(os.path.join(self.panes, "focus-lentago-brasenia")))

    def test_stale_beacon_removes_pane(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        self.clock.advance(601)
        self.producer.cycle()
        self.assertFalse(os.path.exists(os.path.join(self.panes, "focus-lentago-brasenia")))
        self.assertEqual(os.listdir(self.focus), [])

    def test_cleanup_only_touches_its_own_dirs(self):
        other = os.path.join(self.panes, "brief-morning")
        claimed = os.path.join(self.panes, "focus-by-hand")
        orphan = os.path.join(self.panes, "focus-lentago-gone")
        for d in (other, claimed, orphan):
            os.makedirs(d)
        with open(os.path.join(claimed, "manifest.json"), "w") as fh:
            json.dump({"author": "chris@thinkpad", "class": "focus"}, fh)
        with open(os.path.join(orphan, "manifest.json"), "w") as fh:
            json.dump({"author": "focus-producer@pub", "repo": "lentago/gone"}, fh)
        self.producer.cycle()
        self.assertTrue(os.path.isdir(other))
        self.assertTrue(os.path.isdir(claimed))
        self.assertFalse(os.path.exists(orphan))

    def test_pipeline_row(self):
        self.t.set("http://pub.lan/viewport/pipeline.json", [
            {"repo": "lentago/kalmia", "sha": "1111111", "stage": "live", "since": "2026-10-07T11:00:00Z"},
            {"repo": "lentago/brasenia", "sha": "2222222aaaa", "stage": "review",
             "since": "2026-10-07T11:00:00Z"},
        ])
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        page = self.read("focus-lentago-brasenia", "pane.html")
        self.assertIn("pipeline: <b>review</b> · 2222222", page)
        self.assertNotIn("1111111", page)

    def test_pipeline_absent_omits_row(self):
        self.beacon("thinkpad-19ca7047")
        self.producer.cycle()
        self.assertNotIn("pipeline:", self.read("focus-lentago-brasenia", "pane.html"))

    def test_bad_payload_for_one_repo_does_not_stall_the_rest(self):
        self.t.set("https://api.github.com/repos/lentago/kalmia/pulls?state=open&per_page=100",
                   [{"number": 1}])  # no title, head, ...
        self.beacon("thinkpad-19ca7047")
        self.beacon("worker-bbbbbbbb", repo="lentago/kalmia")
        orphan = os.path.join(self.panes, "focus-lentago-gone")
        os.makedirs(orphan)
        self.producer.cycle()
        self.assertTrue(os.path.exists(self.pane("focus-lentago-brasenia", "manifest.json")))
        self.assertFalse(os.path.exists(orphan))

    def test_null_repo_beacon_makes_no_pane(self):
        self.beacon("thinkpad-19ca7047", repo=None)
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.panes) and os.listdir(self.panes))


if __name__ == "__main__":
    unittest.main()
