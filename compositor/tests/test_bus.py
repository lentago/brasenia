import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


    def test_writes_the_rubric_board(self):
        self.write_pane("one", self.manifest())
        self.tick({})
        with open(self.p["board"], encoding="utf-8") as f:
            page = f.read()
        self.assertIsNotNone(bus.board.key_of(page))
        self.assertIn('<span class="chip showing">one</span>', page)
        self.assertNotIn("<script", page)

    def test_an_unchanged_board_is_not_rewritten_within_a_minute(self):
        now = datetime.now(timezone.utc)
        pointer = {"pane": None, "fallback": "status", "url": "http://pub.lan/viewport/status.html",
                   "title": "t", "class": None, "priority": None}
        brief = {"present": False, "mtime": None}
        os.makedirs(self.p["viewport"])
        bus.write_board(self.p["board"], pointer, [], brief, now, "http://pub.lan")
        first = os.stat(self.p["board"]).st_mtime_ns
        bus.write_board(self.p["board"], pointer, [], brief, now + timedelta(seconds=5), "http://pub.lan")
        self.assertEqual(os.stat(self.p["board"]).st_mtime_ns, first)
        # A changed decision is written at once.
        pointer = dict(pointer, fallback="briefing", url="http://pub.lan/brief/")
        bus.write_board(self.p["board"], pointer, [], {"present": True, "mtime": now}, now, "http://pub.lan")
        with open(self.p["board"], encoding="utf-8") as f:
            self.assertIn("Fallback: the morning brief", f.read())


    def test_the_status_card_and_board_use_the_given_zone(self):
        bus.tick(self.webroot, "http://pub.lan", {}, T0, self.lines.append,
                 tz=ZoneInfo("America/New_York"))
        with open(self.p["status"], encoding="utf-8") as f:
            self.assertIn("Status since 08:00 EDT (2026-10-07)", f.read())
        with open(self.p["board"], encoding="utf-8") as f:
            self.assertIn("Generated 8:00:00 AM EDT", f.read())

    def test_cli_rejects_an_unknown_zone(self):
        with self.assertRaises(SystemExit):
            main(["--webroot", self.webroot, "--once", "--tz", "Mars/Olympus"])


    def signal(self, *records):
        os.makedirs(os.path.dirname(self.p["signals"]), exist_ok=True)
        with open(self.p["signals"], "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_an_override_reorders_the_rubric(self):
        self.write_pane("focus-pane", self.manifest("focus"))
        self.write_pane("ambient-pane", self.manifest("ambient"))
        state = self.tick({})
        self.assertEqual(self.current()["pane"], "focus-pane")
        self.signal({"ts": rubric.iso(T0), "id": "priority.ambient", "action": "set", "label": "90"})
        state = self.tick(state, 5)
        self.assertEqual((self.current()["pane"], self.current()["priority"]), ("ambient-pane", 90))
        self.assertIn("settings: priority.ambient=90", self.lines)
        with open(self.p["settings"]) as f:
            doc = json.load(f)
        self.assertEqual(doc["overrides"], {"priority.ambient": 90})
        self.assertEqual(doc["effective"]["priority.ambient"], 90)
        with open(self.p["board"], encoding="utf-8") as f:
            board_page = f.read()
        self.assertIn('<span class="ovr">default 40</span>', board_page)
        self.assertIn("ambient priority set to 90", board_page)
        self.signal({"ts": rubric.iso(T0), "id": "priority.ambient", "action": "undo"})
        self.tick(state, 10)
        self.assertEqual(self.current()["pane"], "focus-pane")
        self.assertIn("settings: all defaults", self.lines)

    def test_a_stale_brief_falls_through_to_the_status_card_under_a_limit(self):
        os.makedirs(os.path.dirname(self.p["brief"]))
        open(self.p["brief"], "w").close()
        old = (T0 - timedelta(days=58)).timestamp()
        os.utime(self.p["brief"], (old, old))
        state = self.tick({})
        self.assertEqual(self.current()["fallback"], "briefing")
        self.signal({"id": "briefing.max_age_hours", "action": "set", "label": "36"})
        self.tick(state, 5)
        self.assertEqual(self.current()["fallback"], "status")
        with open(self.p["board"], encoding="utf-8") as f:
            self.assertIn("older than the 36 h limit", f.read())

    def test_writes_the_configurator_page(self):
        self.tick({})
        with open(self.p["configure"], encoding="utf-8") as f:
            self.assertIn('const ENDPOINT = "/api/signals/rubric";', f.read())


if __name__ == "__main__":
    unittest.main()
