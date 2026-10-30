import json
import os
import shutil
import sys
import tempfile
import time
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

    def write_briefing(self, manifest=None):
        os.makedirs(os.path.dirname(self.p["briefing"]), exist_ok=True)
        with open(self.p["briefing"], "w") as f:
            f.write("<p>briefing</p>")
        if manifest is not None:
            with open(self.p["briefing_manifest"], "w") as f:
                f.write(manifest if isinstance(manifest, str) else json.dumps(manifest))

    def test_empty_bus_with_brief(self):
        self.write_briefing({"schema": 1, "title": "Family Brief",
                             "published": rubric.iso(T0 - timedelta(hours=5)), "author": "a@b"})
        self.tick({})
        self.assertEqual(self.current()["fallback"], "briefing")
        self.assertEqual(self.current()["url"], "http://pub.lan/viewport/briefing/pane.html")
        self.assertEqual(self.current()["title"], "Family Brief")
        self.assertFalse(os.path.exists(self.p["status"]))

    def test_briefing_without_a_readable_manifest_uses_the_file_time(self):
        self.write_briefing("not json")
        self.tick({})
        self.assertEqual(self.current()["title"], rubric.BRIEFING_TITLE)
        with open(self.p["board"], encoding="utf-8") as f:
            self.assertIn("Fallback: the briefing (Briefing)", f.read())

    def test_empty_bus_without_brief_writes_the_status_card(self):
        self.tick({})
        self.assertEqual(self.current()["fallback"], "status")
        with open(self.p["status"]) as f:
            card = f.read()
        self.assertIn("No live pane", card)
        self.assertIn("width: 1920px; height: 1080px", card)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', card)
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
            self.assertIn("Fallback: the briefing", f.read())


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
        # The age comes from the manifest, not the (freshly rewritten) file.
        self.write_briefing({"schema": 1, "title": "Family Brief",
                             "published": rubric.iso(T0 - timedelta(days=58)), "author": "a@b"})
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


    def lineup(self):
        with open(self.p["lineup"]) as f:
            return json.load(f)

    def test_lineup_lists_live_panes_in_rank_order_then_the_briefing(self):
        self.write_pane("focus-a", self.manifest("focus", title="A"))
        self.write_pane("alert-b", self.manifest("alert", title="B"))
        self.write_pane("old", self.manifest("focus", created=rubric.iso(T0 - timedelta(hours=2))))
        self.write_briefing({"schema": 1, "title": "Family Brief", "published": rubric.iso(T0),
                             "author": "a@b", "pane": "family-today"})
        self.tick({})
        doc = self.lineup()
        self.assertEqual([(i["id"], i["showing"]) for i in doc["items"]],
                         [("alert-b", True), ("focus-a", False), ("_briefing", False)])
        self.assertEqual(doc["items"][0]["url"], "http://pub.lan/viewport/panes/alert-b/pane.html")
        self.assertEqual(doc["items"][-1]["url"], "http://pub.lan/viewport/briefing/pane.html")
        self.assertEqual(doc["items"][-1]["title"], "Family Brief")
        self.assertEqual(doc["decided_at"], self.current()["decided_at"])

    def test_lineup_skips_the_briefing_while_its_pane_is_live(self):
        self.write_pane("family-today", self.manifest("ambient", title="Family"))
        self.write_briefing({"schema": 1, "title": "Family Brief", "published": rubric.iso(T0),
                             "author": "a@b", "pane": "family-today"})
        self.tick({})
        self.assertEqual([i["id"] for i in self.lineup()["items"]], ["family-today"])

    def test_lineup_marks_the_briefing_when_it_is_the_fallback(self):
        self.write_briefing({"schema": 1, "title": "Family Brief", "published": rubric.iso(T0),
                             "author": "a@b"})
        self.tick({})
        self.assertEqual([(i["id"], i["showing"]) for i in self.lineup()["items"]],
                         [("_briefing", True)])

    def test_empty_lineup_without_panes_or_briefing(self):
        self.tick({})
        self.assertEqual(self.lineup()["items"], [])


    def test_a_default_resting_pane_set_from_the_remote(self):
        self.write_pane("family-today", self.manifest("ambient", title="Today", dwell_s=60))
        self.write_pane("family-week", self.manifest("ambient", title="Week", dwell_s=60,
                                                     created=rubric.iso(T0 - timedelta(minutes=1))))
        state = self.tick({})
        # No default: the first resting pane by id shows, and nothing rotates.
        self.assertEqual((self.current()["pane"], self.current()["rotation"]), ("family-today", None))
        self.signal({"ts": rubric.iso(T0), "id": "default.pane", "action": "set",
                     "label": "family-week", "client": "192.168.139.21"})
        state = self.tick(state, 5)
        self.assertEqual((self.current()["pane"], self.current()["rotation"]), ("family-week", None))
        self.assertEqual([(i["id"], i["default"]) for i in self.lineup()["items"]],
                         [("family-week", True), ("family-today", False)])
        with open(self.p["board"], encoding="utf-8") as f:
            board_page = f.read()
        self.assertIn('<span class="chip showing">family-week · default</span>', board_page)
        self.assertIn("Default resting pane set to family-week · from 192.168.139.21", board_page)
        with open(self.p["configure"], encoding="utf-8") as f:
            self.assertIn('<option value="family-week" selected>Week</option>', f.read())

    def write_page(self, pane_id, text):
        with open(os.path.join(self.p["panes"], pane_id, "pane.html"), "w") as f:
            f.write(text)

    def test_rev_follows_the_content_not_the_file_time(self):
        self.write_pane("home", self.manifest("ambient"))
        state = self.tick({})
        first = self.current()
        self.assertEqual(len(first["rev"]), 12)
        self.write_page("home", "<p>pane</p>")      # rewritten, same bytes
        state = self.tick(state, 30)
        self.assertEqual(self.current(), first)
        self.write_page("home", "<p>new</p>")
        self.tick(state, 60)
        self.assertNotEqual(self.current()["rev"], first["rev"])
        self.assertEqual(self.current()["decided_at"], "2026-10-07T12:01:00Z")

    def test_a_same_size_rewrite_within_a_second_is_not_missed(self):
        self.write_pane("home", self.manifest("ambient"))
        path = os.path.join(self.p["panes"], "home", "pane.html")
        st = os.stat(path)
        first = bus.page_rev(path)
        with open(path, "w") as f:
            f.write("<p>pan2</p>")                  # same size
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))   # same mtime
        self.assertNotEqual(bus.page_rev(path), first)

    def test_an_old_page_is_hashed_once(self):
        self.write_pane("home", self.manifest("ambient"))
        path = os.path.join(self.p["panes"], "home", "pane.html")
        old = time.time() - 60
        os.utime(path, (old, old))
        first = bus.page_rev(path)
        self.assertIn(path, bus._REV_CACHE)
        self.assertEqual(bus.page_rev(path), first)

    def test_a_renewal_rewrites_expires_at_without_a_decision_line(self):
        self.write_pane("home", self.manifest("ambient"))
        state = self.tick({})
        self.lines.clear()
        self.write_pane("home", self.manifest("ambient", created=rubric.iso(T0 + timedelta(minutes=1))))
        self.tick(state, 60)
        self.assertEqual(self.current()["decided_at"], "2026-10-07T12:00:00Z")
        self.assertEqual(self.current()["expires_at"], "2026-10-07T12:11:00Z")
        self.assertEqual([l for l in self.lines if l.startswith("decision:")], [])

    def test_lineup_items_carry_rev_and_source(self):
        self.write_pane("home", self.manifest("ambient"))
        link = os.path.join(self.p["panes"], "pr-93")
        os.makedirs(link)
        with open(os.path.join(link, "manifest.json"), "w") as f:
            json.dump(self.manifest("attention", source={"url": "https://example.test/pr/93"}), f)
        bus.tick(self.webroot, "http://pub.lan", {}, T0, self.lines.append, link_panes=True)
        items = {i["id"]: i for i in self.lineup()["items"]}
        self.assertEqual(items["pr-93"]["url"], "https://example.test/pr/93")
        self.assertEqual(items["pr-93"]["source"]["theme"], "dark")
        self.assertEqual(len(items["home"]["rev"]), 12)
        self.assertIsNone(items["home"]["source"])
        self.assertEqual(self.current()["pane"], "pr-93")

    def test_link_panes_are_off_by_default(self):
        link = os.path.join(self.p["panes"], "pr-93")
        os.makedirs(link)
        with open(os.path.join(link, "manifest.json"), "w") as f:
            json.dump(self.manifest("attention", source={"url": "https://example.test/pr/93"}), f)
        self.tick({})
        self.assertEqual(self.current()["fallback"], "status")
        self.assertEqual(self.lineup()["items"], [])
        self.assertTrue(any("link panes are off" in l for l in self.lines))

    def test_standing_slots_in_the_log_and_on_the_board(self):
        label = json.dumps({"title": "Open PRs", "url": "https://github.com/pulls"})
        self.signal({"ts": rubric.iso(T0), "id": "link.prs", "action": "set", "label": label,
                     "client": "192.168.139.50"})
        state = self.tick({})
        self.assertIn("settings: link.prs=https://github.com/pulls", self.lines)
        with open(self.p["board"], encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Standing slot prs set to Open PRs (https://github.com/pulls)", page)
        self.assertIn("Every setting is at its default. 1 standing slot.", page)
        self.signal({"ts": rubric.iso(T0), "id": "link.prs", "action": "undo"})
        self.tick(state, 5)
        with open(self.p["board"], encoding="utf-8") as f:
            self.assertIn("Standing slot prs removed", f.read())

    def test_the_link_panes_flag_turns_them_on(self):
        link = os.path.join(self.p["panes"], "pr-93")
        os.makedirs(link)
        with open(os.path.join(link, "manifest.json"), "w") as f:
            # main() runs at the real clock, so the pane must be live now
            json.dump(self.manifest("attention", created=rubric.iso(datetime.now(timezone.utc)),
                                    source={"url": "https://example.test/pr/93"}), f)
        self.assertEqual(main(["--webroot", self.webroot, "--once", "--link-panes"]), 0)
        self.assertEqual(self.current()["url"], "https://example.test/pr/93")


if __name__ == "__main__":
    unittest.main()
