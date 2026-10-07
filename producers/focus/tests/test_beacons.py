import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from focus_producer.producer import pane_id, read_beacons

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def beacon(repo="lentago/brasenia", origin="operator", ts="2026-10-07T11:59:30Z", **extra):
    b = {"schema": 1, "host": "thinkpad", "session": "19ca7047", "repo": repo,
         "cwd": "/home/cpitzi/repos/x", "origin": origin, "ts": ts}
    b.update(extra)
    return b


class BeaconTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, body):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body))

    def test_groups_by_repo_operator_wins(self):
        self.put("thinkpad-aaaaaaaa.json", beacon(origin="fleet"))
        self.put("worker1-bbbbbbbb.json", beacon(origin="operator"))
        self.put("worker2-cccccccc.json", beacon(repo="lentago/kalmia", origin="fleet"))
        self.assertEqual(read_beacons(self.dir, NOW),
                         {"lentago/brasenia": "operator", "lentago/kalmia": "fleet"})

    def test_operator_then_fleet_stays_operator(self):
        self.put("a-00000001.json", beacon(origin="operator"))
        self.put("b-00000002.json", beacon(origin="fleet"))
        self.assertEqual(read_beacons(self.dir, NOW), {"lentago/brasenia": "operator"})

    def test_stale_and_unparseable_beacons_are_deleted(self):
        self.put("old-00000001.json", beacon(ts="2026-10-07T11:49:59Z"))
        self.put("bad-00000002.json", "{not json")
        self.put("nots-00000003.json", {"repo": "lentago/brasenia"})
        self.put("edge-00000004.json", beacon(ts="2026-10-07T11:50:00Z"))
        self.assertEqual(read_beacons(self.dir, NOW), {"lentago/brasenia": "operator"})
        self.assertEqual(sorted(os.listdir(self.dir)), ["edge-00000004.json"])

    def test_null_repo_is_kept_but_ignored(self):
        self.put("a-00000001.json", beacon(repo=None))
        self.assertEqual(read_beacons(self.dir, NOW), {})
        self.assertEqual(os.listdir(self.dir), ["a-00000001.json"])

    def test_partial_files_are_ignored(self):
        self.put("a-00000001.json.partial", "{half")
        self.assertEqual(read_beacons(self.dir, NOW), {})
        self.assertEqual(os.listdir(self.dir), ["a-00000001.json.partial"])

    def test_missing_dir_is_empty(self):
        self.assertEqual(read_beacons(os.path.join(self.dir, "nope"), NOW), {})


class PaneIdTests(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(pane_id("lentago/brasenia"), "focus-lentago-brasenia")
        self.assertEqual(pane_id("lentago/.github"), "focus-lentago--github")
        self.assertEqual(pane_id("Lentago/Shared_Workflows.v2"), "focus-lentago-shared-workflows-v2")


if __name__ == "__main__":
    unittest.main()
