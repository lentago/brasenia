"""Tests for the standing-slots producer. Run from producers/links:
python3 -m unittest discover -s tests"""

import errno
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from links_producer import producer  # noqa: E402
from links_producer.__main__ import main  # noqa: E402

T0 = datetime(2026, 10, 29, 21, 0, 0, tzinfo=timezone.utc)
SOURCE = {"url": "https://github.com/lentago/brasenia/pulls", "theme": "dark", "screens": 1,
          "viewport": [1280, 720], "refresh_s": 60}


class Cycle(unittest.TestCase):

    def setUp(self):
        self.webroot = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.webroot)
        self.viewport = os.path.join(self.webroot, "viewport")
        os.makedirs(os.path.join(self.viewport, "panes"))
        self.now = T0
        self.p = producer.Producer(self.webroot, clock=lambda: self.now)

    def settings(self, slots, **other):
        eff = dict(other)
        eff.update({"link." + k: v for k, v in slots.items()})
        with open(os.path.join(self.viewport, "rubric.json"), "w") as f:
            json.dump({"schema": 1, "effective": eff}, f)

    def pane(self, pane_id):
        d = os.path.join(self.viewport, "panes", pane_id)
        return sorted(os.listdir(d)) if os.path.isdir(d) else None

    def manifest(self, pane_id):
        with open(os.path.join(self.viewport, "panes", pane_id, "manifest.json")) as f:
            return json.load(f)

    def foreign(self, pane_id, author="ann@a"):
        d = os.path.join(self.viewport, "panes", pane_id)
        os.makedirs(d)
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump({"author": author}, f)

    def test_a_slot_becomes_a_resting_link_pane(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}}, **{"priority.focus": 50})
        self.p.cycle()
        self.assertEqual(self.pane("prs"), ["manifest.json"])
        self.assertEqual(self.manifest("prs"), {
            "schema": 1, "class": "ambient", "title": "Open PRs", "created": "2026-10-29T21:00:00Z",
            "ttl_minutes": 10, "author": "links-producer@pub", "origin": "operator", "dwell_s": 60,
            "source": SOURCE})

    def test_each_cycle_renews_it(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        self.now = T0 + timedelta(seconds=30)
        self.p.cycle()
        self.assertEqual(self.manifest("prs")["created"], "2026-10-29T21:00:30Z")

    def test_a_removed_slot_takes_its_pane_down(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE},
                       "status": {"title": "Status", "source": SOURCE}})
        self.p.cycle()
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        self.assertIsNone(self.pane("status"))
        self.assertEqual(self.pane("prs"), ["manifest.json"])

    def test_other_authors_panes_are_left_alone(self):
        self.foreign("prs")
        self.foreign("fleet", "fleet-producer@pub")
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        with self.assertLogs(producer.log, "INFO") as logs:
            self.p.cycle()
            self.p.cycle()
        self.assertEqual(self.manifest("prs"), {"author": "ann@a"})
        self.assertEqual(self.manifest("fleet"), {"author": "fleet-producer@pub"})
        self.assertEqual(len([l for l in logs.output if "belongs to ann@a" in l]), 1)

    def test_a_slot_takes_its_pane_once_the_other_author_lets_go(self):
        self.foreign("prs")
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        shutil.rmtree(os.path.join(self.viewport, "panes", "prs"))
        self.p.cycle()
        self.assertEqual(self.manifest("prs")["author"], "links-producer@pub")

    def test_a_write_cut_off_before_the_rename_does_not_wedge_the_slot(self):
        d = os.path.join(self.viewport, "panes", "prs")
        os.makedirs(d)
        with open(os.path.join(d, "manifest.json.partial"), "w") as f:
            json.dump({"author": "links-producer@pub"}, f)
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        self.assertEqual(self.manifest("prs")["title"], "Open PRs")
        self.settings({})
        self.p.cycle()
        self.assertIsNone(self.pane("prs"))

    def test_a_bad_pane_id_is_never_a_path(self):
        self.settings({"../escape": {"title": "x", "source": SOURCE}, "Bad": {"title": "x", "source": SOURCE}})
        self.p.cycle()
        self.assertEqual(os.listdir(os.path.join(self.viewport, "panes")), [])

    def test_unreadable_settings_change_nothing(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        with open(os.path.join(self.viewport, "rubric.json"), "w") as f:
            f.write("{")
        self.p.cycle()
        self.assertEqual(self.pane("prs"), ["manifest.json"])

    def test_misshapen_slots_are_skipped(self):
        self.settings({"bad": {"title": 3, "source": SOURCE}, "worse": "x",
                       "good": {"title": "Good", "source": SOURCE}})
        self.p.cycle()
        self.assertIsNone(self.pane("bad"))
        self.assertIsNone(self.pane("worse"))
        self.assertEqual(self.pane("good"), ["manifest.json"])

    def staging(self):
        return os.path.join(self.viewport, "staging")

    def test_a_new_pane_appears_in_one_rename(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(os.path.dirname(src), self.viewport),
                            os.path.relpath(dst, self.viewport)))
            self.assertEqual(os.listdir(src), ["manifest.json"])
            return real(src, dst)

        with mock.patch.object(producer.os, "rename", spy):
            self.p.cycle()
        self.assertEqual(renames, [("staging", os.path.join("panes", "prs"))])
        self.assertEqual(os.listdir(self.staging()), [])
        self.assertEqual(self.manifest("prs")["author"], "links-producer@pub")

    def appears_first(self, author):
        """Patch the create rename so that ``author``'s pane lands at the
        target just before it: the race of #51."""
        real = os.rename

        def racer(src, dst):
            if dst == os.path.join(self.viewport, "panes", "prs"):
                os.makedirs(dst)
                with open(os.path.join(dst, "manifest.json"), "w") as f:
                    json.dump({"author": author, "title": "first"}, f)
            return real(src, dst)

        return mock.patch.object(producer.os, "rename", racer)

    def test_a_slot_that_loses_the_race_leaves_the_winner_alone(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        with self.appears_first("ann@a"), self.assertLogs(producer.log, "INFO") as logs:
            self.p.cycle()
        self.assertEqual(self.manifest("prs"), {"author": "ann@a", "title": "first"})
        self.assertTrue(any("belongs to ann@a" in l for l in logs.output))
        self.assertEqual(os.listdir(self.staging()), [])

    def test_losing_the_race_to_itself_updates_in_place(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        with self.appears_first("links-producer@pub"):
            self.p.cycle()
        self.assertEqual(self.manifest("prs")["title"], "Open PRs")
        self.assertEqual(self.pane("prs"), ["manifest.json"])
        self.assertEqual(os.listdir(self.staging()), [])

    def test_an_existing_pane_is_rewritten_by_write_then_rename(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        order = []
        real = os.replace

        def spy(src, dst):
            order.append((os.path.basename(src), os.path.basename(dst)))
            return real(src, dst)

        with mock.patch.object(producer.os, "replace", spy):
            self.p.cycle()
        self.assertEqual(order, [("manifest.json.partial", "manifest.json")])

    def test_a_removed_slots_pane_comes_off_in_one_rename_into_staging(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        self.settings({})
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(src, self.viewport),
                            os.path.relpath(os.path.dirname(dst), self.viewport)))
            return real(src, dst)

        with mock.patch.object(producer.os, "rename", spy):
            self.p.cycle()
        self.assertEqual(renames, [(os.path.join("panes", "prs"), "staging")])
        self.assertIsNone(self.pane("prs"))
        self.assertEqual(os.listdir(self.staging()), [])

    def test_a_removal_across_filesystems_falls_back_to_deleting_in_place(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.p.cycle()
        self.settings({})
        with mock.patch.object(producer.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.p.cycle()
        self.assertIsNone(self.pane("prs"))

    def test_a_removal_that_fails_is_logged_and_the_cycle_goes_on(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}, "b": {"title": "B", "source": SOURCE}})
        self.p.cycle()
        self.settings({"b": {"title": "B", "source": SOURCE}})
        with mock.patch.object(producer, "remove_pane", side_effect=PermissionError("denied")), \
                self.assertLogs(producer.log, "WARNING") as logs:
            self.p.cycle()
        self.assertIn("could not take its pane down", logs.output[0])
        self.assertEqual(self.pane("b"), ["manifest.json"])

    def test_main_runs_one_cycle(self):
        self.settings({"prs": {"title": "Open PRs", "source": SOURCE}})
        self.assertEqual(main(["--webroot", self.webroot, "--once"]), 0)
        self.assertEqual(self.pane("prs"), ["manifest.json"])


if __name__ == "__main__":
    unittest.main()
