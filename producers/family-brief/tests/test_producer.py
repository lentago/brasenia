import json
import os
import shutil
import tempfile
import unittest

from helpers import Clock, fixture, with_date
from family_brief_producer.producer import AUTHOR, DWELL_S, PANE_ID, WEEK_ID, Producer


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.webroot = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.webroot)
        self.pane_dir = os.path.join(self.webroot, "viewport", "panes", PANE_ID)
        self.doc = fixture()
        self.clock = Clock()
        self.producer = Producer(self.webroot, "file:///unused",
                                 fetch=lambda url: json.dumps(self.doc).encode(), clock=self.clock)

    def manifest(self):
        with open(os.path.join(self.pane_dir, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_fresh_brief_writes_pane_then_manifest(self):
        self.producer.cycle()
        self.assertEqual(sorted(os.listdir(self.pane_dir)), ["detail.html", "manifest.json", "pane.html"])
        m = self.manifest()
        self.assertEqual((m["class"], m["ttl_minutes"], m["author"], m["origin"]),
                         ("ambient", 30, AUTHOR, "operator"))
        self.assertEqual(m["created"], "2026-10-25T15:00:00Z")

    def test_each_cycle_renews(self):
        self.producer.cycle()
        self.clock.advance(1)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-10-25T16:00:00Z")

    def test_today_follows_the_household_clock(self):
        # 03:30 UTC on the 26th is still the 25th in New York.
        self.clock.now = self.clock.now.replace(day=26, hour=3, minute=30)
        self.producer.cycle()
        with open(os.path.join(self.pane_dir, "pane.html"), encoding="utf-8") as fh:
            self.assertIn("<h1>Sunday, October 25</h1>", fh.read())

    def test_stale_brief_removes_the_pane(self):
        self.producer.cycle()
        self.doc = with_date(self.doc, "2026-10-23")
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_unreachable_source_leaves_the_pane(self):
        self.producer.cycle()

        def broken(url):
            raise OSError("down")
        self.producer.fetch = broken
        self.clock.advance(1)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-10-25T15:00:00Z")

    def test_someone_elses_pane_is_left_alone(self):
        os.makedirs(self.pane_dir)
        with open(os.path.join(self.pane_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"author": "someone@else"}, fh)
        self.producer.cycle()
        self.assertEqual(os.listdir(self.pane_dir), ["manifest.json"])

    def briefing(self, name):
        with open(os.path.join(self.webroot, "viewport", "briefing", name), encoding="utf-8") as fh:
            return fh.read()

    def test_fresh_brief_also_fills_the_briefing_slot(self):
        self.producer.cycle()
        d = os.path.join(self.webroot, "viewport", "briefing")
        self.assertEqual(sorted(os.listdir(d)), ["detail.html", "manifest.json", "pane.html"])
        m = json.loads(self.briefing("manifest.json"))
        self.assertEqual(m, {"schema": 1, "title": "Family Brief",
                             "published": "2026-10-25T11:10:49Z", "author": AUTHOR,
                             "pane": "family-today"})
        self.assertIn("<h1>Sunday, October 25</h1>", self.briefing("pane.html"))

    def test_a_stale_brief_leaves_the_briefing_slot_saying_how_old(self):
        self.doc = with_date(self.doc, "2026-10-23")
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))
        self.assertIn("No brief since Fri 10/23", self.briefing("pane.html"))
        self.assertIn("No brief since Fri 10/23", self.briefing("detail.html"))

    def test_published_falls_back_to_the_brief_date(self):
        del self.doc["generated_at"]
        self.producer.cycle()
        self.assertEqual(json.loads(self.briefing("manifest.json"))["published"], "2026-10-25T00:00:00Z")

    def test_someone_elses_briefing_slot_is_left_alone(self):
        d = os.path.join(self.webroot, "viewport", "briefing")
        os.makedirs(d)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"author": "someone@else"}, fh)
        self.producer.cycle()
        self.assertEqual(os.listdir(d), ["manifest.json"])
        # The pane is unaffected.
        self.assertTrue(os.path.exists(os.path.join(self.pane_dir, "pane.html")))


    def test_both_resting_panes_are_written_with_a_slow_dwell(self):
        self.producer.cycle()
        week = os.path.join(self.webroot, "viewport", "panes", WEEK_ID)
        self.assertEqual(sorted(os.listdir(week)), ["detail.html", "manifest.json", "pane.html"])
        for d in (self.pane_dir, week):
            with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
                m = json.load(fh)
            self.assertEqual((m["class"], m["dwell_s"], m["author"]), ("ambient", DWELL_S, AUTHOR))
        with open(os.path.join(week, "pane.html"), encoding="utf-8") as fh:
            self.assertIn("<h1>This week", fh.read())

    def test_a_stale_brief_removes_both_resting_panes(self):
        self.producer.cycle()
        self.doc = with_date(self.doc, "2026-10-23")
        self.producer.cycle()
        self.assertFalse(os.path.exists(os.path.join(self.webroot, "viewport", "panes", WEEK_ID)))
        self.assertFalse(os.path.exists(self.pane_dir))
