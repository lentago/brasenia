import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from compositor import rubric  # noqa: E402
from compositor.rubric import decide  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
BASE = "http://pub.lan"


def pane(pane_id, cls="focus", origin=None, created=T0, ttl=10, dwell=None,
         files=("pane.html", "manifest.json"), **extra):
    manifest = {
        "schema": 1,
        "class": cls,
        "title": "%s title" % pane_id,
        "created": rubric.iso(created),
        "ttl_minutes": ttl,
        "author": "test@unit",
    }
    if origin is not None:
        manifest["origin"] = origin
    if dwell is not None:
        manifest["dwell_s"] = dwell
    manifest.update(extra)
    return {"id": pane_id, "files": set(files), "manifest": manifest}


def run(panes, now=T0, state=None, **kw):
    return decide(panes, now, state if state is not None else {}, **kw)


class Ranking(unittest.TestCase):

    def test_priority_wins(self):
        pointer, _ = run([pane("calm", "ambient"), pane("busy", "activity"),
                          pane("focus-a", "focus")])
        self.assertEqual(pointer["pane"], "busy")
        self.assertEqual(pointer["class"], "activity")
        self.assertEqual(pointer["priority"], 60)

    def test_every_class_has_its_v1_priority(self):
        self.assertEqual(rubric.PRIORITY, {
            "alert": 100, "attention": 80, "live": 70, "activity": 60,
            "focus": 50, "ambient": 40, "briefing": 0})

    def test_operator_breaks_the_tie_within_a_class(self):
        # Created later, so recency alone would pick the fleet pane.
        pointer, state = run([
            pane("focus-fleet", origin="fleet", created=T0),
            pane("focus-laptop", origin="operator",
                 created=T0 - timedelta(minutes=5))])
        self.assertEqual(pointer["pane"], "focus-laptop")
        self.assertIsNone(pointer["rotation"])
        self.assertIsNone(state["rotation"])

    def test_origin_defaults_to_fleet(self):
        pointer, _ = run([pane("focus-default"),
                          pane("focus-op", origin="operator",
                               created=T0 - timedelta(minutes=1))])
        self.assertEqual(pointer["pane"], "focus-op")

    def test_origin_never_crosses_priority(self):
        pointer, _ = run([pane("focus-op", origin="operator"),
                          pane("job", "activity", origin="fleet")])
        self.assertEqual(pointer["pane"], "job")

    def test_rotation_starts_with_the_newest(self):
        pointer, _ = run([
            pane("older", origin="operator", created=T0 - timedelta(minutes=2)),
            pane("newer", origin="operator", created=T0 - timedelta(minutes=1))])
        self.assertEqual(pointer["pane"], "newer")
        self.assertEqual(pointer["rotation"], {"index": 0, "of": 2,
                                               "dwell_s": 20})

    def test_pointer_shape(self):
        pointer, _ = run([pane("focus-lentago-brasenia",
                               title="brasenia — open pull requests")],
                         now=T0 + timedelta(seconds=5))
        self.assertEqual(pointer, {
            "schema": 1,
            "decided_at": "2026-10-07T12:00:05Z",
            "pane": "focus-lentago-brasenia",
            "url": "http://pub.lan/viewport/panes/focus-lentago-brasenia/"
                   "pane.html",
            "class": "focus",
            "priority": 50,
            "title": "brasenia — open pull requests",
            "expires_at": "2026-10-07T12:10:00Z",
            "fallback": None,
            "rotation": None,
            "rev": None,
            "source": None,
        })

    def test_url_base_is_used_without_double_slash(self):
        pointer, _ = run([pane("p")], url_base="http://example.test/")
        self.assertEqual(pointer["url"],
                         "http://example.test/viewport/panes/p/pane.html")


class Rotation(unittest.TestCase):

    def ops(self, dwell_a=None, dwell_b=None):
        return [pane("a", origin="operator", created=T0, dwell=dwell_a),
                pane("b", origin="operator", created=T0 - timedelta(seconds=1),
                     dwell=dwell_b)]

    def step(self, panes, seconds, state):
        return decide(panes, T0 + timedelta(seconds=seconds), state)

    def test_two_operator_panes_rotate_every_dwell(self):
        panes = self.ops()
        shown = []
        state = {}
        for t in range(0, 85, 5):
            pointer, state = self.step(panes, t, state)
            shown.append(pointer["pane"])
        self.assertEqual(shown, ["a"] * 4 + ["b"] * 4 + ["a"] * 4 + ["b"] * 4
                         + ["a"])

    def test_each_pane_keeps_its_own_dwell(self):
        panes = self.ops(dwell_a=10, dwell_b=30)
        state, shown = {}, []
        for t in range(0, 50, 5):
            pointer, state = self.step(panes, t, state)
            shown.append((pointer["pane"], pointer["rotation"]["dwell_s"]))
        self.assertEqual(shown, [("a", 10)] * 2 + [("b", 30)] * 6
                         + [("a", 10)] * 2)

    def test_attention_preempts_at_once(self):
        panes = self.ops()
        pointer, state = self.step(panes, 0, {})
        self.assertEqual(pointer["pane"], "a")
        pointer, state = self.step(
            panes + [pane("blocked", "attention", ttl=240)], 5, state)
        self.assertEqual(pointer["pane"], "blocked")
        self.assertEqual(pointer["decided_at"], "2026-10-07T12:00:05Z")
        self.assertIsNone(pointer["rotation"])

    def test_rotation_restarts_when_the_group_returns(self):
        panes = self.ops()
        _, state = self.step(panes, 0, {})
        _, state = self.step(panes, 25, state)  # b showing
        _, state = self.step(panes + [pane("x", "alert")], 30, state)
        pointer, _ = self.step(panes, 35, state)
        self.assertEqual(pointer["pane"], "a")

    def test_lower_groups_wait(self):
        panes = self.ops() + [pane("c", origin="fleet")]
        state, seen = {}, set()
        for t in range(0, 200, 5):
            pointer, state = self.step(panes, t, state)
            seen.add(pointer["pane"])
        self.assertEqual(seen, {"a", "b"})

    def test_successor_takes_the_slot_of_a_released_pane(self):
        panes = self.ops() + [pane("c", origin="operator",
                                   created=T0 - timedelta(seconds=2))]
        _, state = self.step(panes, 0, {})
        pointer, state = self.step(panes, 20, state)
        self.assertEqual(pointer["pane"], "b")
        pointer, state = self.step([panes[0], panes[2]], 25, state)
        self.assertEqual(pointer["pane"], "c")
        self.assertEqual(pointer["rotation"]["of"], 2)

    def test_unchanged_decision_keeps_decided_at(self):
        panes = self.ops()
        first, state = self.step(panes, 0, {})
        again, state = self.step(panes, 5, state)
        self.assertIs(again, first)
        self.assertEqual(again["decided_at"], "2026-10-07T12:00:00Z")
        moved, _ = self.step(panes, 20, state)
        self.assertEqual(moved["decided_at"], "2026-10-07T12:00:20Z")


class Liveness(unittest.TestCase):

    def test_expired_pane_never_wins(self):
        expired = pane("old-alert", "alert", created=T0 - timedelta(hours=2),
                       ttl=60)
        pointer, state = run([expired, pane("calm", "ambient")])
        self.assertEqual(pointer["pane"], "calm")
        self.assertEqual(state["skipped"], {})

    def test_expiry_is_exclusive(self):
        at_edge = pane("edge", created=T0 - timedelta(minutes=10), ttl=10)
        pointer, _ = run([at_edge])
        self.assertEqual(pointer["fallback"], "briefing")

    def test_partial_files_never_win(self):
        cases = [
            ("pane.html.partial", "manifest.json"),
            ("pane.html", "manifest.json.partial"),
            ("pane.html",),
            ("manifest.json",),
        ]
        for files in cases:
            with self.subTest(files=files):
                pointer, state = run([pane("writing", "alert", files=files),
                                      pane("calm", "ambient")])
                self.assertEqual(pointer["pane"], "calm")
                self.assertEqual(state["skipped"], {})

    def test_a_stale_partial_beside_final_files_is_ignored(self):
        pointer, _ = run([pane("p", files=("pane.html", "manifest.json",
                                           "pane.html.partial"))])
        self.assertEqual(pointer["pane"], "p")


class Malformed(unittest.TestCase):

    def bad(self, **changes):
        p = pane("bad", "alert")
        for key, value in changes.items():
            if value is KeyError:
                del p["manifest"][key]
            else:
                p["manifest"][key] = value
        return p

    def test_malformed_manifests_are_skipped_with_a_reason(self):
        cases = {
            "missing title": self.bad(title=KeyError),
            "missing author": self.bad(author=KeyError),
            "unknown class": self.bad(**{"class": "pr-review"}),
            "naive created": self.bad(created="2026-10-07T12:00:00"),
            "garbage created": self.bad(created="yesterday"),
            "zero ttl": self.bad(ttl_minutes=0),
            "string ttl": self.bad(ttl_minutes="10"),
            "boolean ttl": self.bad(ttl_minutes=True),
            "unknown origin": self.bad(origin="laptop"),
            "bad dwell": self.bad(dwell_s=-1),
        }
        for name, p in cases.items():
            with self.subTest(name):
                pointer, state = run([p, pane("calm", "ambient")])
                self.assertEqual(pointer["pane"], "calm")
                self.assertIn("bad", state["skipped"])

    def test_undecodable_and_non_object_manifests(self):
        for manifest in (rubric.Malformed("manifest does not parse: x"),
                         ["not", "an", "object"], None):
            with self.subTest(manifest=manifest):
                p = pane("bad", "alert")
                p["manifest"] = manifest
                pointer, state = run([p])
                self.assertEqual(pointer["fallback"], "briefing")
                self.assertIn("bad", state["skipped"])

    def test_invalid_pane_id(self):
        for pane_id in ("Upper", "-leading", "has_underscore", "x" * 64,
                        ".hidden"):
            with self.subTest(pane_id=pane_id):
                pointer, state = run([pane(pane_id, "alert")])
                self.assertEqual(state["skipped"],
                                 {pane_id: "invalid pane id"})
                self.assertEqual(pointer["fallback"], "briefing")

    def test_out_of_range_ttl_or_created_is_skipped_not_fatal(self):
        panes = [pane("huge", ttl=1e300), pane("inf", ttl=float("inf")),
                 pane("edge", created=datetime(9999, 12, 31, 23, 0,
                                               tzinfo=timezone.utc), ttl=120)]
        pointer, state = run(panes)
        self.assertEqual(pointer["fallback"], "briefing")
        self.assertEqual(set(state["skipped"]), {"huge", "inf", "edge"})
        for reason in state["skipped"].values():
            self.assertIn("out of range", reason)

    def test_offsets_and_optional_fields_are_accepted(self):
        p = pane("ok", created=T0, repo="lentago/brasenia",
                 done_when="pr-merged")
        p["manifest"]["created"] = "2026-10-07T08:00:00-04:00"
        pointer, state = run([p])
        self.assertEqual(pointer["pane"], "ok")
        self.assertEqual(pointer["expires_at"], "2026-10-07T12:10:00Z")


class Fallback(unittest.TestCase):

    def test_empty_bus_points_at_the_briefing(self):
        pointer, _ = run([])
        self.assertEqual(pointer["fallback"], "briefing")
        self.assertEqual(pointer["url"], "http://pub.lan/viewport/briefing/pane.html")
        self.assertEqual(pointer["title"], rubric.BRIEFING_TITLE)
        titled, _ = run([], briefing_title="Family Brief")
        self.assertEqual(titled["title"], "Family Brief")
        self.assertIsNone(pointer["pane"])
        self.assertIsNone(pointer["expires_at"])
        self.assertIsNone(pointer["rotation"])

    def test_no_brief_points_at_the_status_card(self):
        pointer, _ = run([], brief_present=False)
        self.assertEqual(pointer["fallback"], "status")
        self.assertEqual(pointer["url"],
                         "http://pub.lan/viewport/status.html")
        self.assertIsNone(pointer["pane"])
        self.assertTrue(pointer["title"])

    def test_only_dead_panes_fall_back(self):
        pointer, _ = run([pane("old", created=T0 - timedelta(hours=1))],
                         brief_present=False)
        self.assertEqual(pointer["fallback"], "status")

    def test_a_live_pane_beats_the_fallback(self):
        pointer, _ = run([pane("calm", "ambient")], brief_present=False)
        self.assertEqual(pointer["pane"], "calm")
        self.assertIsNone(pointer["fallback"])



class Explain(unittest.TestCase):

    def explain(self, panes, now=T0, **kw):
        pointer, _ = run(panes, now=now, **kw)
        return pointer, {r["id"]: r for r in rubric.explain(panes, now, pointer)}

    def test_showing_rotating_and_outranked(self):
        panes = [pane("a", "focus", origin="operator"),
                 pane("b", "focus", origin="operator", created=T0 - timedelta(minutes=1)),
                 pane("c", "focus", origin="fleet"),
                 pane("d", "ambient")]
        pointer, rows = self.explain(panes)
        self.assertEqual(pointer["pane"], "a")
        self.assertEqual(rows["a"]["status"], "showing")
        self.assertEqual(rows["b"]["status"], "rotating")
        self.assertIn("takes turns with a", rows["b"]["reason"])
        self.assertEqual(rows["c"]["status"], "outranked")
        self.assertIn("operator panes go first", rows["c"]["reason"])
        self.assertEqual(rows["d"]["status"], "outranked")
        self.assertIn("lower priority than a (focus 50)", rows["d"]["reason"])

    def test_dead_panes_say_why(self):
        panes = [pane("old", ttl=1, created=T0 - timedelta(minutes=5)),
                 pane("half", files=("pane.html",)),
                 pane("bad", cls="nonsense"),
                 pane("Bad_Id")]
        pointer, rows = self.explain(panes)
        self.assertEqual(pointer["fallback"], "briefing")
        self.assertEqual(rows["old"]["status"], "expired")
        self.assertIn("expired at", rows["old"]["reason"])
        self.assertEqual((rows["half"]["status"], rows["half"]["reason"]),
                         ("writing", "no manifest.json yet"))
        self.assertEqual(rows["bad"]["status"], "malformed")
        self.assertIn("unknown class", rows["bad"]["reason"])
        self.assertEqual(rows["Bad_Id"]["status"], "invalid")

    def test_live_panes_come_first_in_rank_order(self):
        panes = [pane("z-dead", ttl=1, created=T0 - timedelta(minutes=5)),
                 pane("low", "ambient"), pane("high", "alert")]
        pointer, _ = run(panes)
        ids = [r["id"] for r in rubric.explain(panes, T0, pointer)]
        self.assertEqual(ids, ["high", "low", "z-dead"])



class DefaultPane(unittest.TestCase):

    def test_the_default_resting_pane_wins_its_rung_and_holds(self):
        panes = [pane("today", "ambient", dwell=60), pane("week", "ambient", dwell=60,
                                                          created=T0 - timedelta(minutes=1))]
        pointer, _ = run(panes)
        self.assertEqual((pointer["pane"], pointer["rotation"]["of"]), ("today", 2))
        pointer, state = run(panes, default_pane="week")
        self.assertEqual(pointer["pane"], "week")
        self.assertIsNone(pointer["rotation"])
        rows = {r["id"]: r for r in rubric.explain(panes, T0, pointer, default_pane="week")}
        self.assertEqual(rows["today"]["status"], "outranked")
        self.assertIn("default resting pane", rows["today"]["reason"])

    def test_urgent_panes_still_win_over_the_default(self):
        panes = [pane("week", "ambient"), pane("pr", "focus")]
        pointer, _ = run(panes, default_pane="week")
        self.assertEqual(pointer["pane"], "pr")

    def test_only_an_ambient_pane_can_be_the_default(self):
        panes = [pane("a", "focus"), pane("b", "focus", created=T0 - timedelta(minutes=1))]
        pointer, _ = run(panes, default_pane="b")
        self.assertEqual(pointer["rotation"]["of"], 2)   # still taking turns

    def test_an_absent_default_changes_nothing(self):
        panes = [pane("today", "ambient")]
        pointer, _ = run(panes, default_pane="gone")
        self.assertEqual(pointer["pane"], "today")


class RestingOrder(unittest.TestCase):
    """Resting panes keep a fixed order by id, whenever each was rewritten (#86)."""

    def resting(self, stamps):
        return [pane(pid, "ambient", origin="operator", dwell=60, created=T0 - timedelta(seconds=s))
                for pid, s in stamps]

    def test_resting_panes_rank_by_id_not_by_created(self):
        for stamps in ([("weather", 0), ("home", 5), ("fleet", 9)],
                       [("fleet", 0), ("weather", 3), ("home", 7)]):
            panes = self.resting(stamps)
            pointer, _ = run(panes)
            ids = [r["id"] for r in rubric.explain(panes, T0, pointer)]
            self.assertEqual(ids, ["fleet", "home", "weather"])

    def test_rotation_order_survives_rewrites(self):
        state, shown = {}, []
        for t in range(0, 240, 30):
            # each cycle, a different producer was the last to rewrite
            order = [("fleet", t % 7), ("home", (t + 3) % 7), ("weather", (t + 5) % 7)]
            pointer, state = decide(self.resting(order), T0 + timedelta(seconds=t), state)
            shown.append(pointer["pane"])
        self.assertEqual(shown, ["fleet", "fleet", "home", "home",
                                 "weather", "weather", "fleet", "fleet"])

    def test_the_default_still_comes_first(self):
        panes = self.resting([("fleet", 0), ("home", 0), ("weather", 0)])
        pointer, _ = run(panes, default_pane="weather")
        ids = [r["id"] for r in rubric.explain(panes, T0, pointer, default_pane="weather")]
        self.assertEqual(ids, ["weather", "fleet", "home"])

    def test_other_classes_still_rank_newest_first(self):
        panes = [pane("a-older", "attention", created=T0 - timedelta(minutes=2), ttl=240),
                 pane("b-newer", "attention", created=T0 - timedelta(minutes=1), ttl=240)]
        pointer, _ = run(panes)
        self.assertEqual(pointer["pane"], "b-newer")


class Revision(unittest.TestCase):
    """#96: the pointer carries the shown pane's content revision, so new
    content is a new decision and a renewal is not."""

    def rev_pane(self, rev, created=T0):
        p = pane("home", "ambient", created=created)
        p["rev"] = rev
        return p

    def test_the_pointer_carries_the_rev(self):
        pointer, _ = run([self.rev_pane("abc123")])
        self.assertEqual(pointer["rev"], "abc123")

    def test_new_content_is_a_new_decision(self):
        first, state = run([self.rev_pane("aaa")])
        later, _ = run([self.rev_pane("bbb")], now=T0 + timedelta(seconds=30), state=state)
        self.assertEqual(later["decided_at"], "2026-10-07T12:00:30Z")
        self.assertEqual(later["rev"], "bbb")

    def test_a_renewal_keeps_decided_at_but_moves_expires_at(self):
        first, state = run([self.rev_pane("aaa")])
        renewed = self.rev_pane("aaa", created=T0 + timedelta(minutes=1))
        later, _ = run([renewed], now=T0 + timedelta(minutes=1), state=state)
        self.assertEqual(later["decided_at"], first["decided_at"])
        self.assertEqual(later["expires_at"], "2026-10-07T12:11:00Z")

    def test_the_briefing_carries_its_rev(self):
        pointer, _ = run([], brief_rev="b71ef")
        self.assertEqual((pointer["fallback"], pointer["rev"]), ("briefing", "b71ef"))


class LinkPanes(unittest.TestCase):
    """#96, ADR-0016: a pane whose manifest names a web page."""

    URL = "https://github.com/lentago/brasenia/pull/93"

    def link(self, pane_id="pr-93", source=None, cls="attention", **kw):
        return pane(pane_id, cls, files=("manifest.json",),
                    source=source if source is not None else {"url": self.URL}, **kw)

    def test_shown_when_link_panes_are_on(self):
        pointer, _ = run([self.link()], link_panes=True)
        self.assertEqual(pointer["pane"], "pr-93")
        self.assertEqual(pointer["url"], self.URL)
        self.assertEqual(pointer["source"], {"url": self.URL, "theme": "dark", "screens": 1,
                                             "viewport": [1280, 720], "refresh_s": 60})
        self.assertEqual(pointer["rev"], rubric.source_rev(pointer["source"]))

    def test_skipped_with_a_reason_while_off(self):
        pointer, state = run([self.link(), pane("calm", "ambient")])
        self.assertEqual(pointer["pane"], "calm")
        self.assertEqual(state["skipped"], {"pr-93": rubric.LINK_PANES_OFF})
        row = rubric.explain([self.link()], T0, pointer)[0]
        self.assertEqual((row["status"], row["reason"]), ("off", rubric.LINK_PANES_OFF))

    def test_a_file_pane_still_needs_pane_html(self):
        pointer, _ = run([pane("half", files=("manifest.json",))], link_panes=True)
        self.assertEqual(pointer["fallback"], "briefing")

    def test_settings_are_kept_and_unknown_keys_dropped(self):
        source = {"url": self.URL, "theme": "light", "screens": 2,
                  "viewport": [1920, 1080], "refresh_s": 300, "zoom": 2}
        pointer, _ = run([self.link(source=source)], link_panes=True)
        self.assertEqual(pointer["source"], {"url": self.URL, "theme": "light", "screens": 2,
                                             "viewport": [1920, 1080], "refresh_s": 300})

    def test_a_new_source_is_a_new_revision(self):
        a = rubric.parse_source({"url": self.URL})
        b = rubric.parse_source({"url": self.URL, "theme": "light"})
        self.assertNotEqual(rubric.source_rev(a), rubric.source_rev(b))

    def test_bad_sources_are_malformed(self):
        bad = [
            ("not-a-dict", "source is not a JSON object"),
            ({"url": "file:///etc/passwd"}, "not an http(s) URL"),
            ({"url": "https://"}, "not an http(s) URL"),
            ({"url": "https://x.test/a b"}, "is not a URL"),
            ({"url": self.URL, "theme": "sepia"}, "source.theme"),
            ({"url": self.URL, "screens": 5}, "source.screens"),
            ({"url": self.URL, "screens": True}, "source.screens"),
            ({"url": self.URL, "viewport": [100, 720]}, "source.viewport"),
            ({"url": self.URL, "viewport": [1280]}, "source.viewport"),
            ({"url": self.URL, "refresh_s": 5}, "source.refresh_s"),
            ({"url": self.URL, "refresh_s": float("inf")}, "source.refresh_s"),
            ({"url": "https://ann:hunter2@x.test/"}, "carries credentials"),
            ({"url": "https://ann@x.test/"}, "carries credentials"),
        ]
        for source, reason in bad:
            with self.subTest(source=source):
                pointer, state = run([self.link(source=source)], link_panes=True)
                self.assertEqual(pointer["fallback"], "briefing")
                self.assertIn(reason, state["skipped"]["pr-93"])

    def test_an_infinite_dwell_is_malformed(self):
        pointer, state = run([pane("a", dwell=float("inf")), pane("b")])
        self.assertIn("dwell_s", state["skipped"]["a"])
        self.assertEqual(pointer["pane"], "b")

    def test_an_old_style_pane_is_unchanged(self):
        pointer, _ = run([pane("focus-x")], link_panes=True)
        self.assertEqual(pointer["url"], "http://pub.lan/viewport/panes/focus-x/pane.html")
        self.assertIsNone(pointer["source"])


if __name__ == "__main__":
    unittest.main()
