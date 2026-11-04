import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from helpers import NOW, Queue, pr

from fleet_producer import producer
from fleet_producer.github import GitHubError
from fleet_producer.producer import Producer


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Search:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def __call__(self):
        self.calls += 1
        if self.fail:
            raise GitHubError("search answered HTTP 403")
        return 1, [pr("lentago/brasenia", 87, "Fix the thing", 2)]


class ProducerTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.jobs = os.path.join(self.root, "jobs")
        self.webroot = os.path.join(self.root, "www")
        self.pane_dir = os.path.join(self.webroot, "viewport", "panes", "fleet")
        Queue(self.jobs).worker("claude-runner")
        self.clock = Clock()
        self.search = Search()
        self.p = Producer(self.webroot, self.jobs, "America/New_York", self.search, self.clock)

    def read(self, name):
        with open(os.path.join(self.pane_dir, name), encoding="utf-8") as fh:
            return json.load(fh) if name.endswith(".json") else fh.read()

    def test_writes_the_pane_and_its_manifest(self):
        self.p.cycle()
        self.assertEqual(self.read("manifest.json"), {
            "schema": 1, "class": "ambient", "title": "Fleet", "created": "2026-10-29T00:40:00Z",
            "ttl_minutes": 10, "author": "fleet-producer@pub", "origin": "operator", "dwell_s": 60})
        self.assertIn("<b>brasenia</b> #87", self.read("pane.html"))
        self.assertEqual(sorted(os.listdir(self.pane_dir)), ["manifest.json", "pane.html"])

    def test_no_mount_no_pane(self):
        p = Producer(self.webroot, os.path.join(self.root, "absent"), search=self.search, clock=self.clock)
        p.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_searches_every_five_minutes(self):
        self.p.cycle()
        self.clock.now += timedelta(seconds=240)
        self.p.cycle()
        self.assertEqual(self.search.calls, 1)
        self.clock.now += timedelta(seconds=60)
        self.p.cycle()
        self.assertEqual(self.search.calls, 2)

    def test_a_failed_search_keeps_the_last_list_with_its_time(self):
        self.p.cycle()
        self.search.fail = True
        self.clock.now += timedelta(seconds=300)
        self.p.cycle()
        page = self.read("pane.html")
        self.assertIn("<b>brasenia</b> #87", page)
        self.assertIn("agent PRs as of 8:40 PM", page)

    def test_someone_elses_pane_is_left_alone(self):
        os.makedirs(self.pane_dir)
        with open(os.path.join(self.pane_dir, "manifest.json"), "w") as fh:
            json.dump({"author": "someone@else"}, fh)
        with self.assertLogs(producer.log, "WARNING"):
            self.p.cycle()
        self.assertEqual(os.listdir(self.pane_dir), ["manifest.json"])

    def staging(self):
        return os.path.join(self.webroot, "viewport", "staging")

    def test_a_new_pane_appears_in_one_rename(self):
        renames = []
        real = os.rename

        def spy(src, dst):
            bus = os.path.join(self.webroot, "viewport")
            renames.append((os.path.relpath(os.path.dirname(src), bus), os.path.relpath(dst, bus)))
            self.assertEqual(sorted(os.listdir(src)), ["manifest.json", "pane.html"])
            return real(src, dst)

        with mock.patch.object(producer.os, "rename", spy):
            self.p.cycle()
        self.assertEqual(renames, [("staging", os.path.join("panes", "fleet"))])
        self.assertEqual(os.listdir(self.staging()), [])
        self.assertEqual(self.read("manifest.json")["author"], "fleet-producer@pub")

    def appears_first(self, author):
        """Patch the create rename so that ``author``'s pane lands at the
        target just before it: the race of #51."""
        real = os.rename

        def racer(src, dst):
            if dst == self.pane_dir:
                os.makedirs(dst)
                with open(os.path.join(dst, "pane.html"), "w") as fh:
                    fh.write("<p>first</p>")
                with open(os.path.join(dst, "manifest.json"), "w") as fh:
                    json.dump({"author": author, "title": "first"}, fh)
            return real(src, dst)

        return mock.patch.object(producer.os, "rename", racer)

    def test_a_cycle_that_loses_the_race_leaves_the_winner_alone(self):
        with self.appears_first("someone@else"), self.assertLogs(producer.log, "WARNING"):
            self.p.cycle()
        self.assertEqual(self.read("manifest.json"), {"author": "someone@else", "title": "first"})
        self.assertEqual(self.read("pane.html"), "<p>first</p>")
        self.assertEqual(os.listdir(self.staging()), [])

    def test_losing_the_race_to_itself_updates_in_place(self):
        with self.appears_first("fleet-producer@pub"):
            self.p.cycle()
        self.assertEqual(self.read("manifest.json")["title"], "Fleet")
        self.assertIn("<b>brasenia</b> #87", self.read("pane.html"))
        self.assertEqual(sorted(os.listdir(self.pane_dir)), ["manifest.json", "pane.html"])
        self.assertEqual(os.listdir(self.staging()), [])

    def test_an_existing_pane_is_rewritten_file_by_file_manifest_last(self):
        self.p.cycle()
        order = []
        real = os.replace

        def spy(src, dst):
            order.append((os.path.basename(src), os.path.basename(dst)))
            return real(src, dst)

        self.clock.now += timedelta(seconds=60)
        with mock.patch.object(producer.os, "replace", spy):
            self.p.cycle()
        self.assertEqual(order, [("pane.html.partial", "pane.html"),
                                 ("manifest.json.partial", "manifest.json")])


if __name__ == "__main__":
    unittest.main()
