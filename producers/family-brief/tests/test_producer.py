import json
import os
import shutil
import tempfile
import unittest

from helpers import Clock, fixture, with_date
from family_brief_producer.producer import AUTHOR, PANE_ID, Producer


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
