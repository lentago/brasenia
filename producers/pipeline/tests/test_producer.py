import errno
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

from helpers import Clock, fixture, landed
from pipeline_producer import __main__ as cli
from pipeline_producer import producer as producer_module
from pipeline_producer.producer import Producer


class ProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.webroot = os.path.join(self.tmp.name, "www")
        self.served = os.path.join(self.tmp.name, "served")  # stands in for pub.lan
        os.makedirs(os.path.join(self.served, "viewport"))
        self.pane_dir = os.path.join(self.webroot, "viewport", "panes", "change-pipeline")
        self.clock = Clock()
        self.producer = Producer(self.webroot, "file://" + self.served + "/", clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def serve(self, doc):
        with open(os.path.join(self.served, "viewport", "pipeline.json"), "w") as fh:
            json.dump(doc, fh)

    def read(self, name):
        with open(os.path.join(self.pane_dir, name), encoding="utf-8") as fh:
            return fh.read()

    def manifest(self):
        return json.loads(self.read("manifest.json"))

    def test_nothing_in_flight_no_pane(self):
        self.serve(fixture("example"))
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_one_in_flight_writes_pane_and_manifest(self):
        self.serve(landed(fixture("in-flight"), "lentago/kalmia"))
        self.producer.cycle()
        self.assertEqual(sorted(os.listdir(self.pane_dir)), ["manifest.json", "pane.html"])
        self.assertEqual(self.manifest(), {
            "schema": 1, "class": "activity", "title": "1 change in flight",
            "created": "2026-10-07T22:11:00Z", "ttl_minutes": 15,
            "author": "pipeline-producer@pub", "origin": "operator",
        })
        page = self.read("pane.html")
        self.assertIn("<b>drosera</b> · head 9f1c2ab", page)
        self.assertIn("stuck 9 min", page)
        self.assertIn("alloy-lxc105 · lagging", page)
        self.assertEqual(page.count('class="strip'), 1)
        self.assertEqual(page.count('<svg class="edge go"'), 1)

    def test_renewed_every_cycle_while_in_flight(self):
        doc = fixture("in-flight")
        self.serve(doc)
        self.producer.cycle()
        self.clock.advance(1)
        doc["generated_at"] = "2026-10-07T22:11:30Z"
        self.serve(doc)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-10-07T22:12:00Z")

    def test_stale_document_keeps_pane_without_renewing(self):
        self.serve(fixture("in-flight"))
        self.producer.cycle()
        before = self.read("pane.html")
        self.clock.advance(6)  # generated_at is now 7 min old
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-10-07T22:11:00Z")
        page = self.read("pane.html")
        self.assertIn("no fresh pipeline data, last tried", page)
        self.assertEqual(page.split("<!--asof-->")[0], before.split("<!--asof-->")[0])
        self.clock.advance(10)  # past created + 15 min
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_missing_document_keeps_pane(self):
        self.serve(fixture("in-flight"))
        self.producer.cycle()
        os.unlink(os.path.join(self.served, "viewport", "pipeline.json"))
        self.clock.advance(1)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-10-07T22:11:00Z")
        self.assertIn("no fresh pipeline data", self.read("pane.html"))

    def test_missing_document_and_no_pane_writes_nothing(self):
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_changed_document_rewrites_pane(self):
        doc = fixture("in-flight")
        self.serve(doc)
        self.producer.cycle()
        self.assertIn("terraform apply · in progress", self.read("pane.html"))
        kalmia = doc["repos"][2]
        kalmia["stages"][4].update(state=2, detail="terraform apply · failure")
        kalmia["stuck"] = True
        doc["generated_at"] = "2026-10-07T22:11:30Z"
        self.serve(doc)
        self.clock.advance(1)
        self.producer.cycle()
        page = self.read("pane.html")
        self.assertIn("terraform apply · failure", page)
        self.assertNotIn("in progress", page)
        self.assertEqual(page.count('class="strip stuck"'), 2)

    def test_cleanup_when_last_repo_lands(self):
        doc = fixture("in-flight")
        self.serve(doc)
        self.producer.cycle()
        doc = landed(doc, "lentago/kalmia")
        self.serve(doc)
        self.producer.cycle()
        self.assertEqual(self.manifest()["title"], "1 change in flight")
        self.serve(landed(doc, "lentago/drosera"))
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_someone_elses_pane_is_left_alone(self):
        os.makedirs(self.pane_dir)
        foreign = {"schema": 1, "class": "alert", "title": "mine", "created": "2026-10-07T22:00:00Z",
                   "ttl_minutes": 60, "author": "chris@thinkpad"}
        with open(os.path.join(self.pane_dir, "manifest.json"), "w") as fh:
            json.dump(foreign, fh)
        for doc in (fixture("in-flight"), fixture("example")):
            self.serve(doc)
            self.producer.cycle()
            self.assertEqual(self.manifest(), foreign)

    def test_unreadable_manifest_is_left_alone(self):
        os.makedirs(self.pane_dir)
        with open(os.path.join(self.pane_dir, "manifest.json"), "w") as fh:
            fh.write("{not json")
        with open(os.path.join(self.pane_dir, "pane.html"), "w") as fh:
            fh.write("<html>someone's page</html>")
        for doc in (fixture("in-flight"), fixture("example")):
            self.serve(doc)
            self.producer.cycle()
            self.assertEqual(self.read("manifest.json"), "{not json")
            self.assertEqual(self.read("pane.html"), "<html>someone's page</html>")

    def test_odd_stage_state_renders_grey_instead_of_crashing(self):
        doc = fixture("in-flight")
        flying = [r for r in doc["repos"] if r.get("in_flight")][0]
        flying["stages"][2]["state"] = ["3"]
        flying["stages"][3]["state"] = {"state": 3}
        flying["stages"][4]["state"] = True
        self.serve(doc)
        self.producer.cycle()
        self.assertTrue(os.path.exists(os.path.join(self.pane_dir, "pane.html")))

    def bus(self, *parts):
        return os.path.join(self.webroot, "viewport", *parts)

    def test_a_new_pane_appears_in_one_rename(self):
        self.serve(fixture("in-flight"))
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(os.path.dirname(src), self.bus()), os.path.relpath(dst, self.bus())))
            self.assertEqual(sorted(os.listdir(src)), ["manifest.json", "pane.html"])
            return real(src, dst)

        with mock.patch.object(producer_module.os, "rename", spy):
            self.producer.cycle()
        self.assertEqual(renames, [("staging", os.path.join("panes", "change-pipeline"))])
        self.assertEqual(os.listdir(self.bus("staging")), [])
        self.assertEqual(self.manifest()["author"], "pipeline-producer@pub")

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

        return mock.patch.object(producer_module.os, "rename", racer)

    def test_a_cycle_that_loses_the_race_leaves_the_winner_alone(self):
        self.serve(fixture("in-flight"))
        with self.appears_first("chris@thinkpad"):
            self.producer.cycle()
        self.assertEqual(self.manifest(), {"author": "chris@thinkpad", "title": "first"})
        self.assertEqual(self.read("pane.html"), "<p>first</p>")
        self.assertEqual(os.listdir(self.bus("staging")), [])

    def test_losing_the_race_to_itself_updates_in_place(self):
        self.serve(fixture("in-flight"))
        with self.appears_first("pipeline-producer@pub"):
            self.producer.cycle()
        self.assertEqual(self.manifest()["title"], "2 changes in flight")
        self.assertIn("<b>drosera</b>", self.read("pane.html"))
        self.assertEqual(os.listdir(self.bus("staging")), [])

    def test_an_existing_pane_is_rewritten_file_by_file_manifest_last(self):
        doc = fixture("in-flight")
        self.serve(doc)
        self.producer.cycle()
        order = []
        real = os.replace

        def spy(src, dst):
            order.append((os.path.basename(src), os.path.basename(dst)))
            return real(src, dst)

        self.clock.advance(1)
        doc["generated_at"] = "2026-10-07T22:11:30Z"
        self.serve(doc)
        with mock.patch.object(producer_module.os, "replace", spy):
            self.producer.cycle()
        self.assertEqual(order, [("pane.html.partial", "pane.html"),
                                 ("manifest.json.partial", "manifest.json")])

    def land_everything(self):
        doc = fixture("in-flight")
        self.serve(doc)
        self.producer.cycle()
        self.serve(landed(landed(doc, "lentago/kalmia"), "lentago/drosera"))

    def test_a_resolved_pane_comes_off_in_one_rename_into_staging(self):
        self.land_everything()
        renames = []
        real = os.rename

        def spy(src, dst):
            renames.append((os.path.relpath(src, self.bus()), os.path.relpath(os.path.dirname(dst), self.bus())))
            return real(src, dst)

        with mock.patch.object(producer_module.os, "rename", spy):
            self.producer.cycle()
        self.assertEqual(renames, [(os.path.join("panes", "change-pipeline"), "staging")])
        self.assertFalse(os.path.exists(self.pane_dir))
        self.assertEqual(os.listdir(self.bus("staging")), [])

    def test_a_removal_across_filesystems_falls_back_to_deleting_in_place(self):
        self.land_everything()
        with mock.patch.object(producer_module.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane_dir))

    def test_a_removal_that_fails_is_logged_not_raised(self):
        self.land_everything()
        with mock.patch.object(producer_module, "remove_pane", side_effect=PermissionError("denied")):
            self.producer.cycle()
        self.assertTrue(os.path.isdir(self.pane_dir))

    def test_cli_once_renders_fixture(self):
        fixtures = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "in-flight")
        rc = cli.main(["--once", "--webroot", self.webroot, "--url-base", "file://" + fixtures,
                       "--now", "2026-10-07T22:11:00Z"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.manifest()["title"], "2 changes in flight")


if __name__ == "__main__":
    unittest.main()
