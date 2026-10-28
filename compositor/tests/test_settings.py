import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from compositor import configure, rubric, settings  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


class Settings(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.log = os.path.join(self.dir, "rubric.jsonl")

    def write(self, *records, raw=""):
        with open(self.log, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            f.write(raw)

    def test_defaults_come_from_the_rubric(self):
        d = settings.defaults()
        for cls in settings.CLASSES:
            self.assertEqual(d["priority." + cls], rubric.PRIORITY[cls])
        self.assertIsNone(d["briefing.max_age_hours"])
        self.assertEqual(d["rotation.dwell_s"], rubric.DEFAULT_DWELL_S)
        self.assertEqual(set(d), set(settings.SPEC))

    def test_missing_log_means_no_overrides(self):
        self.assertEqual(settings.load(self.log), ({}, []))

    def test_latest_valid_action_per_setting_wins(self):
        self.write({"ts": "2026-10-07T11:00:00Z", "id": "priority.focus", "action": "set", "label": "60"},
                   {"ts": "2026-10-07T11:01:00Z", "id": "priority.focus", "action": "set", "label": "5000"},
                   {"ts": "2026-10-07T11:02:00Z", "id": "rotation.dwell_s", "action": "set", "label": "30"},
                   {"ts": "2026-10-07T11:03:00Z", "id": "rotation.dwell_s", "action": "undo"},
                   {"ts": "2026-10-07T11:04:00Z", "id": "briefing.max_age_hours", "action": "set",
                    "label": "36", "client": "192.168.139.50"},
                   raw="not json\n[1, 2]\n")
        overrides, history = settings.load(self.log)
        # 5000 is out of range: rejected, so the earlier 60 stands.
        self.assertEqual(overrides, {"priority.focus": 60, "briefing.max_age_hours": 36})
        self.assertEqual([h["key"] for h in history],
                         ["briefing.max_age_hours", "rotation.dwell_s", "rotation.dwell_s",
                          "priority.focus", "priority.focus"])
        self.assertEqual(history[0]["client"], "192.168.139.50")
        self.assertIn("outside 1-999", history[3]["error"])
        self.assertIsNone(history[4]["error"])

    def test_bad_entries_are_rejected_not_applied(self):
        self.write({"id": "priority.nonsense", "action": "set", "label": "1"},
                   {"id": "priority.alert", "action": "dismiss"},
                   {"id": "priority.alert", "action": "set", "label": "ten"},
                   {"id": "priority.alert", "action": "set"})
        overrides, history = settings.load(self.log)
        self.assertEqual(overrides, {})
        self.assertEqual([h["error"] for h in history][::-1][:2], ["unknown setting", "unknown action"])
        self.assertTrue(all(h["error"] for h in history))

    def test_history_is_capped_newest_first(self):
        self.write(*[{"id": "rotation.dwell_s", "action": "set", "label": str(10 + i)} for i in range(20)])
        overrides, history = settings.load(self.log)
        self.assertEqual(overrides["rotation.dwell_s"], 29)
        self.assertEqual(len(history), settings.HISTORY)
        self.assertEqual(history[0]["value"], 29)

    def test_priorities_keep_briefing_at_zero(self):
        eff = settings.effective({"priority.ambient": 90})
        prio = settings.priorities(eff)
        self.assertEqual((prio["ambient"], prio["focus"], prio["briefing"]), (90, 50, 0))

    def test_brief_usable(self):
        fresh = {"present": True, "mtime": T0 - timedelta(hours=10)}
        old = {"present": True, "mtime": T0 - timedelta(days=58)}
        none = {"present": False, "mtime": None}
        anyage = settings.effective({})
        self.assertEqual(settings.brief_usable(old, anyage, T0), (True, None))
        limit = settings.effective({"briefing.max_age_hours": 36})
        self.assertEqual(settings.brief_usable(fresh, limit, T0), (True, None))
        self.assertEqual(settings.brief_usable(old, limit, T0), (False, "older than the 36 h limit"))
        off = settings.effective({"briefing.max_age_hours": 0})
        self.assertEqual(settings.brief_usable(fresh, off, T0),
                         (False, "the briefing fallback is turned off"))
        self.assertFalse(settings.brief_usable(none, anyage, T0)[0])


class Configure(unittest.TestCase):

    def test_page_has_a_field_per_setting_prefilled(self):
        eff = settings.effective({"priority.focus": 60})
        page, key = configure.render(eff, {"priority.focus": 60})
        self.assertEqual(configure.key_of(page), key)
        for k in settings.SPEC:
            self.assertIn('id="%s"' % k, page)
        self.assertIn('<div class="field overridden"><label for="priority.focus">', page)
        self.assertRegex(page, r'id="priority.focus" name="priority.focus" type="number" min="1" max="999" '
                               r'step="1" value="60" placeholder="50"')
        self.assertRegex(page, r'id="briefing.max_age_hours"[^>]*value="" placeholder="no limit"')
        self.assertIn('const ENDPOINT = "/api/signals/rubric";', page)
        self.assertIn('OVERRIDDEN = ["priority.focus"]', page)

    def test_page_is_self_contained(self):
        page, _ = configure.render(settings.effective({}), {})
        self.assertIsNone(re.search(r'<script[^>]+src=|<link[^>]+href=|(src|href)="https?://(?!pub\.lan)', page))

    def test_key_tracks_content(self):
        _, a = configure.render(settings.effective({}), {})
        _, b = configure.render(settings.effective({}), {})
        _, c = configure.render(settings.effective({"rotation.dwell_s": 30}), {"rotation.dwell_s": 30})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
