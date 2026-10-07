import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from compositor import bus, rubric  # noqa: E402
from compositor.__main__ import main  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


class Bus(unittest.TestCase):

    def setUp(self):
        self.webroot = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.webroot)
        self.p = bus.paths(self.webroot)
        self.lines = []

    def tick(self, state, seconds=0):
        return bus.tick(self.webroot, "http://pub.lan", state,
                        T0 + timedelta(seconds=seconds), self.lines.append)

    def write_pane(self, pane_id, manifest=None, raw=None):
        d = os.path.join(self.p["panes"], pane_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pane.html"), "w") as f:
            f.write("<p>pane</p>")
        with open(os.path.join(d, "manifest.json"), "w") as f:
            f.write(raw if raw is not None else json.dumps(manifest))

    def manifest(self, cls="focus", **extra):
        m = {"schema": 1, "class": cls, "title": "t",
             "created": rubric.iso(T0), "ttl_minutes": 10, "author": "a@b"}
        m.update(extra)
        return m

    def current(self):
        with open(self.p["current"]) as f:
            return json.load(f)

    def test_creates_the_bus_directories(self):
        self.tick({})
        for key in ("panes", "focus", "state"):
            self.assertTrue(os.path.isdir(self.p[key]), key)

    def test_empty_bus_with_brief(self):
        os.makedirs(os.path.dirname(self.p["brief"]))
        open(self.p["brief"], "w").close()
        self.tick({})
        self.assertEqual(self.current()["fallback"], "briefing")
        self.assertFalse(os.path.exists(self.p["status"]))

    def test_empty_bus_without_brief_writes_the_status_card(self):
        self.tick({})
        self.assertEqual(self.current()["fallback"], "status")
        with open(self.p["status"]) as f:
            card = f.read()
        self.assertIn("No live pane", card)
        self.assertIn("width: 1280px; height: 720px", card)
        self.assertEqual(len(self.lines), 1)
        self.assertTrue(self.lines[0].startswith("decision: fallback=status"))

    def test_recreates_a_deleted_status_card(self):
        state = self.tick({})
        self.assertTrue(os.path.isfile(self.p["status"]))
        before = self.current()
        os.remove(self.p["status"])
        state = self.tick(state, seconds=5)
        self.assertTrue(os.path.isfile(self.p["status"]))
        self.assertEqual(self.current(), before)

    def test_rewrites_only_on_change_and_atomically(self):
        self.write_pane("focus-a", self.manifest())
        state = self.tick({})
        ino = os.stat(self.p["current"]).st_ino
        state = self.tick(state, 5)
        state = self.tick(state, 10)
        self.assertEqual(os.stat(self.p["current"]).st_ino, ino)
        self.assertEqual(len(self.lines), 1)
        self.write_pane("alarm", self.manifest("alert"))
        self.tick(state, 15)
        self.assertNotEqual(os.stat(self.p["current"]).st_ino, ino)
        self.assertEqual(self.current()["pane"], "alarm")
        self.assertEqual(self.current()["decided_at"], "2026-10-07T12:00:15Z")
        self.assertEqual(len(self.lines), 2)
        leftovers = [n for n in os.listdir(self.p["viewport"])
                     if n.endswith(".partial")]
        self.assertEqual(leftovers, [])

    def test_restores_a_deleted_pointer_without_a_log_line(self):
        state = self.tick({})
        os.remove(self.p["current"])
        self.tick(state, 5)
        self.assertTrue(os.path.exists(self.p["current"]))
        self.assertEqual(len(self.lines), 1)

    def test_malformed_manifest_is_logged_once_and_kept(self):
        self.write_pane("broken", raw="{not json")
        state = self.tick({})
        state = self.tick(state, 5)
        state = self.tick(state, 10)
        skipped = [l for l in self.lines if l.startswith("skipped:")]
        self.assertEqual(len(skipped), 1)
        self.assertIn("pane=broken", skipped[0])
        self.assertTrue(os.path.exists(
            os.path.join(self.p["panes"], "broken", "manifest.json")))

    def test_state_survives_a_restart(self):
        self.write_pane("focus-a", self.manifest())
        self.tick({})
        restored = bus.load_state(self.p["state"])
        self.tick(restored, 5)
        self.assertEqual(len(self.lines), 1)

    def test_cli_once(self):
        out = os.path.join(self.webroot, "out")
        os.makedirs(out)
        self.assertEqual(main(["--webroot", out, "--once"]), 0)
        self.assertTrue(os.path.exists(os.path.join(out, "viewport",
                                                    "current.json")))


if __name__ == "__main__":
    unittest.main()
