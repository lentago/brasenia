import errno
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import Clock, fixture, with_date
from family_brief_producer import producer as producer_module
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
        self.assertEqual(sorted(os.listdir(self.pane_dir)), ["manifest.json", "pane.html"])
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
        self.assertEqual(sorted(os.listdir(d)), ["manifest.json", "pane.html"])
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

    def test_a_desk_edition_left_by_an_older_producer_is_removed(self):
        briefing = os.path.join(self.webroot, "viewport", "briefing")
        for d in (self.pane_dir, briefing):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "detail.html"), "w", encoding="utf-8") as fh:
                fh.write("<p>old desk edition</p>")
        self.producer.cycle()
        for d in (self.pane_dir, briefing):
            self.assertFalse(os.path.exists(os.path.join(d, "detail.html")), d)

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
        self.assertEqual(sorted(os.listdir(week)), ["manifest.json", "pane.html"])
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

    def bus(self, *parts):
        return os.path.join(self.webroot, "viewport", *parts)

    def test_every_new_pane_appears_in_one_rename(self):
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(os.path.dirname(src), self.bus()), os.path.relpath(dst, self.bus())))
            self.assertEqual(sorted(os.listdir(src)), ["manifest.json", "pane.html"])
            return real(src, dst)

        with mock.patch.object(producer_module.os, "rename", spy):
            self.producer.cycle()
        self.assertEqual(sorted(renames), [("staging", "briefing"),
                                           ("staging", os.path.join("panes", "family-today")),
                                           ("staging", os.path.join("panes", "family-week"))])
        self.assertEqual(os.listdir(self.bus("staging")), [])

    def appears_first(self, target, author):
        """Patch the create rename so that ``author``'s pane lands at
        ``target`` just before it: the race of #51."""
        real = os.rename

        def racer(src, dst):
            if dst == self.bus(*target):
                os.makedirs(dst)
                with open(os.path.join(dst, "pane.html"), "w") as fh:
                    fh.write("<p>first</p>")
                with open(os.path.join(dst, "manifest.json"), "w") as fh:
                    json.dump({"author": author, "title": "first"}, fh)
            return real(src, dst)

        return mock.patch.object(producer_module.os, "rename", racer)

    def test_a_pane_that_loses_the_race_is_left_alone(self):
        with self.appears_first(("panes", PANE_ID), "someone@else"):
            self.producer.cycle()
        self.assertEqual(self.manifest(), {"author": "someone@else", "title": "first"})
        with open(os.path.join(self.pane_dir, "pane.html"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<p>first</p>")
        self.assertEqual(os.listdir(self.bus("staging")), [])
        self.assertTrue(os.path.exists(self.bus("panes", WEEK_ID, "pane.html")))   # the others go on

    def test_the_briefing_slot_that_loses_the_race_is_left_alone(self):
        with self.appears_first(("briefing",), "someone@else"):
            self.producer.cycle()
        self.assertEqual(json.loads(self.briefing("manifest.json")),
                         {"author": "someone@else", "title": "first"})
        self.assertEqual(self.briefing("pane.html"), "<p>first</p>")
        self.assertEqual(os.listdir(self.bus("staging")), [])

    def test_losing_the_race_to_itself_updates_in_place(self):
        for target in (("panes", PANE_ID), ("briefing",)):
            with self.subTest(target=target[-1]), self.appears_first(target, AUTHOR):
                self.producer.cycle()
                with open(self.bus(*target, "pane.html"), encoding="utf-8") as fh:
                    self.assertIn("<h1>", fh.read())   # ours, not the racer's "first"
                with open(self.bus(*target, "manifest.json"), encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["author"], AUTHOR)
                self.assertEqual(os.listdir(self.bus("staging")), [])
            shutil.rmtree(self.bus("panes"))
            shutil.rmtree(self.bus("briefing"))

    def test_an_existing_pane_is_rewritten_file_by_file_manifest_last(self):
        self.producer.cycle()
        order = []
        real = os.replace

        def spy(src, dst):
            order.append(os.path.relpath(dst, self.bus()))
            return real(src, dst)

        self.clock.advance(1)
        with mock.patch.object(producer_module.os, "replace", spy):
            self.producer.cycle()
        self.assertEqual(order, [
            os.path.join("briefing", "pane.html"), os.path.join("briefing", "manifest.json"),
            os.path.join("panes", "family-today", "pane.html"), os.path.join("panes", "family-today", "manifest.json"),
            os.path.join("panes", "family-week", "pane.html"), os.path.join("panes", "family-week", "manifest.json")])

    def stale_after_fresh(self):
        self.producer.cycle()
        self.doc = with_date(self.doc, "2026-10-23")

    def test_stale_panes_come_off_in_one_rename_into_staging(self):
        self.stale_after_fresh()
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(src, self.bus()), os.path.relpath(os.path.dirname(dst), self.bus())))
            return real(src, dst)

        with mock.patch.object(producer_module.os, "rename", spy):
            self.producer.cycle()
        self.assertEqual(renames, [(os.path.join("panes", "family-today"), "staging"),
                                   (os.path.join("panes", "family-week"), "staging")])
        self.assertEqual(os.listdir(self.bus("panes")), [])
        self.assertEqual(os.listdir(self.bus("staging")), [])
        self.assertTrue(os.path.exists(self.bus("briefing", "pane.html")))   # the slot stays

    def test_a_removal_across_filesystems_falls_back_to_deleting_in_place(self):
        self.stale_after_fresh()
        with mock.patch.object(producer_module.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.producer.cycle()
        self.assertEqual(os.listdir(self.bus("panes")), [])

    def test_a_removal_that_fails_is_logged_not_raised(self):
        self.stale_after_fresh()
        with mock.patch.object(producer_module, "remove_pane", side_effect=PermissionError("denied")), \
                self.assertLogs(producer_module.log, "WARNING") as logs:
            self.producer.cycle()
        self.assertIn("could not remove panes/family-today", logs.output[0])
