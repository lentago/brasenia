import json
import os
import random
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
            "alert": 100, "attention": 80, "activity": 60,
            "focus": 50, "ambient": 40, "briefing": 0})

    def test_a_live_pane_is_an_unknown_class(self):
        # RTMP live ingest and its class are retired (#122).
        pointer, state = run([pane("drone", "live"), pane("calm", "ambient")])
        self.assertEqual(pointer["pane"], "calm")
        self.assertEqual(state["skipped"], {"drone": "unknown class 'live'"})

    def test_operator_breaks_the_tie_within_a_class(self):
        # Created later, so recency alone would pick the fleet pane.
        pointer, state = run([
            pane("focus-fleet", origin="fleet", created=T0),
            pane("focus-laptop", origin="operator",
                 created=T0 - timedelta(minutes=5))])
        self.assertEqual(pointer["pane"], "focus-laptop")
        self.assertIsNone(pointer["rotation"])
        self.assertNotIn("rotation", state)

    def test_origin_defaults_to_fleet(self):
        pointer, _ = run([pane("focus-default"),
                          pane("focus-op", origin="operator",
                               created=T0 - timedelta(minutes=1))])
        self.assertEqual(pointer["pane"], "focus-op")

    def test_origin_never_crosses_priority(self):
        pointer, _ = run([pane("focus-op", origin="operator"),
                          pane("job", "activity", origin="fleet")])
        self.assertEqual(pointer["pane"], "job")

    def test_panes_seen_first_together_rank_by_id_not_created(self):
        # Both arrive in the first tick, so created (newest: "b-newer") decides nothing.
        pointer, state = run([
            pane("a-older", origin="operator", created=T0 - timedelta(minutes=2)),
            pane("b-newer", origin="operator", created=T0 - timedelta(minutes=1))])
        self.assertEqual(pointer["pane"], "a-older")
        self.assertIsNone(pointer["rotation"])
        self.assertEqual(state["arrivals"], {"a-older": {"at": "2026-10-07T12:00:00Z"},
                                             "b-newer": {"at": "2026-10-07T12:00:00Z"}})

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


class StrictOrder(unittest.TestCase):
    """ADR-0020: a strict total order and nothing rotates (#121)."""

    def step(self, panes, seconds, state):
        return decide(panes, T0 + timedelta(seconds=seconds), state)

    def ops(self):
        return [pane("a", origin="operator", ttl=60), pane("b", origin="operator", ttl=60)]

    def test_same_rung_panes_never_take_turns(self):
        state, shown = {}, set()
        for t in range(0, 300, 5):
            pointer, state = self.step(self.ops(), t, state)
            shown.add(pointer["pane"])
        self.assertEqual(shown, {"a"})

    def test_an_unchanged_decision_keeps_decided_at(self):
        first, state = self.step(self.ops(), 0, {})
        for t in range(5, 120, 5):
            again, state = self.step(self.ops(), t, state)
            self.assertIs(again, first)
        self.assertEqual(again["decided_at"], "2026-10-07T12:00:00Z")

    def test_a_new_arrival_ranks_first_in_its_rung(self):
        _, state = self.step(self.ops(), 0, {})
        pointer, state = self.step(self.ops() + [pane("c", origin="operator", ttl=60)], 30, state)
        self.assertEqual(pointer["pane"], "c")
        self.assertEqual(pointer["decided_at"], "2026-10-07T12:00:30Z")
        self.assertEqual(state["arrivals"]["c"], {"at": "2026-10-07T12:00:30Z"})
        self.assertEqual(state["arrivals"]["a"], {"at": "2026-10-07T12:00:00Z"})

    def test_renewal_and_a_rewritten_created_never_reorder(self):
        # b arrives after a, so b shows. Then a's producer renews every tick,
        # so a's created is always the newest, and b's falls further behind.
        _, state = self.step([pane("a", origin="operator", ttl=60)], 0, {})
        for t in range(10, 600, 10):
            now = T0 + timedelta(seconds=t)
            panes = [pane("a", origin="operator", created=now, ttl=60),
                     pane("b", origin="operator", created=T0 + timedelta(seconds=10), ttl=60)]
            pointer, state = decide(panes, now, state)
            self.assertEqual(pointer["pane"], "b", t)

    def test_attention_preempts_at_once_and_the_rung_comes_back_unchanged(self):
        pointer, state = self.step(self.ops(), 0, {})
        self.assertEqual(pointer["pane"], "a")
        pointer, state = self.step(self.ops() + [pane("blocked", "attention", ttl=240)], 5, state)
        self.assertEqual(pointer["pane"], "blocked")
        self.assertEqual(pointer["decided_at"], "2026-10-07T12:00:05Z")
        pointer, state = self.step(self.ops(), 10, state)
        self.assertEqual(pointer["pane"], "a")

    def test_lower_panes_wait(self):
        panes = self.ops() + [pane("c", origin="fleet", ttl=60)]
        state, seen = {}, set()
        for t in range(0, 200, 5):
            pointer, state = self.step(panes, t, state)
            seen.add(pointer["pane"])
        self.assertEqual(seen, {"a"})

    def test_a_released_pane_hands_over_to_the_next_in_order(self):
        _, state = self.step([pane("a", origin="operator", ttl=60)], 0, {})
        _, state = self.step([pane("a", origin="operator", ttl=60),
                              pane("b", origin="operator", ttl=60)], 5, state)
        _, state = self.step([pane("a", origin="operator", ttl=60),
                              pane("b", origin="operator", ttl=60),
                              pane("c", origin="operator", ttl=60)], 10, state)
        # Newest first: c, b, a. Release c, and b (the next newest) shows.
        pointer, state = self.step([pane("a", origin="operator", ttl=60),
                                    pane("b", origin="operator", ttl=60)], 15, state)
        self.assertEqual(pointer["pane"], "b")

    def test_a_pane_missing_briefly_keeps_its_place(self):
        # A TTL that lapsed just before its renewal drops "b" for a tick.
        _, state = self.step([pane("a", origin="operator", ttl=60)], 0, {})
        both = [pane("a", origin="operator", ttl=60), pane("b", origin="operator", ttl=60)]
        pointer, state = self.step(both, 5, state)
        self.assertEqual(pointer["pane"], "b")
        pointer, state = self.step([pane("a", origin="operator", ttl=60)], 10, state)
        self.assertEqual(pointer["pane"], "a")
        self.assertEqual(state["arrivals"]["b"], {"at": "2026-10-07T12:00:05Z",
                                                  "gone": "2026-10-07T12:00:10Z"})
        pointer, state = self.step(both, 15, state)
        self.assertEqual(pointer["pane"], "b")
        self.assertEqual(state["arrivals"]["b"], {"at": "2026-10-07T12:00:05Z"})

    def test_a_pane_gone_for_the_grace_window_arrives_again(self):
        grace = int(rubric.ARRIVAL_GRACE.total_seconds())
        a = [pane("a", origin="operator", ttl=60)]
        _, state = self.step(a + [pane("b", origin="operator", ttl=60)], 0, {})
        _, state = self.step(a, 5, state)
        _, state = self.step(a, 5 + grace - 1, state)
        self.assertIn("b", state["arrivals"])
        _, state = self.step(a, 5 + grace, state)
        self.assertNotIn("b", state["arrivals"])
        later = T0 + timedelta(seconds=10 + grace)
        pointer, state = decide(a + [pane("b", origin="operator", created=later, ttl=60)], later, state)
        self.assertEqual(state["arrivals"]["b"], {"at": rubric.iso(later)})
        self.assertEqual(pointer["pane"], "b")   # it arrived again, so it is now the newest

    def test_a_damaged_or_old_state_loads(self):
        old = {"rotation": {"pane": "b", "index": 1, "since": T0.isoformat(), "group": ["a", "b"]},
               "arrivals": {"a": {"at": "garbage"}, "b": "not a record", "c": {"gone": "x"}}}
        pointer, state = self.step(self.ops(), 0, old)
        self.assertEqual(pointer["pane"], "a")
        self.assertEqual(set(state), {"pointer", "arrivals", "skipped"})
        self.assertEqual(state["arrivals"], {"a": {"at": "2026-10-07T12:00:00Z"},
                                             "b": {"at": "2026-10-07T12:00:00Z"}})
        json.dumps(state)

    def test_no_two_live_panes_ever_rank_equal(self):
        # Property test: for any set of live panes (any classes, origins, default
        # and arrival times, including shared ones), the rank keys are distinct,
        # so the order is strict, and the pointer shows the first.
        rng = random.Random(121)
        classes = [c for c in rubric.PRIORITY if c != "briefing"]
        for trial in range(300):
            ids = rng.sample(["p%02d" % i for i in range(40)], rng.randint(1, 12))
            panes = [pane(pid, rng.choice(classes), origin=rng.choice(rubric.ORIGINS),
                          created=T0 - timedelta(seconds=rng.randint(0, 3)), ttl=600)
                     for pid in ids]
            arrivals = {pid: {"at": rubric.iso(T0 - timedelta(seconds=rng.randint(0, 3)))}
                        for pid in ids}
            default = rng.choice(ids + [None])
            priority = dict(rubric.PRIORITY, **{c: rng.choice([40, 50, 60]) for c in classes})
            pointer, state = decide(panes, T0, {"arrivals": arrivals},
                                    default_pane=default, priority=priority)
            live = [rubric.parse_manifest(p["id"], p["manifest"], priority) for p in panes]
            keys = [rubric._rank_key(default, state["arrivals"])(p) for p in live]
            self.assertEqual(len(set(keys)), len(keys), trial)
            first = min(live, key=rubric._rank_key(default, state["arrivals"]))
            self.assertEqual(pointer["pane"], first["id"], trial)


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

    def test_showing_and_outranked(self):
        panes = [pane("a", "focus", origin="operator"),
                 pane("b", "focus", origin="operator", created=T0 - timedelta(minutes=1)),
                 pane("c", "focus", origin="fleet"),
                 pane("d", "ambient")]
        pointer, rows = self.explain(panes)
        self.assertEqual(pointer["pane"], "a")
        self.assertEqual(rows["a"]["status"], "showing")
        self.assertEqual(rows["b"]["status"], "outranked")
        self.assertIn("arrived with a, which comes first by id", rows["b"]["reason"])
        self.assertNotIn("rotating", rubric.STATUSES)
        self.assertEqual(rows["c"]["status"], "outranked")
        self.assertIn("operator panes go first", rows["c"]["reason"])
        self.assertEqual(rows["d"]["status"], "outranked")
        self.assertIn("lower priority than a (focus 50)", rows["d"]["reason"])

    def test_a_later_arrival_says_so(self):
        _, state = run([pane("a", origin="operator")])
        panes = [pane("a", origin="operator"), pane("b", origin="operator")]
        later = T0 + timedelta(seconds=5)
        pointer, state = run(panes, now=later, state=state)
        rows = {r["id"]: r for r in rubric.explain(panes, later, pointer,
                                                   arrivals=state["arrivals"])}
        self.assertEqual(rows["b"]["status"], "showing")
        self.assertEqual(rows["a"]["reason"], "b arrived more recently")

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
        self.assertEqual((pointer["pane"], pointer["rotation"]), ("today", None))
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
        self.assertEqual(pointer["pane"], "a")   # b is not ambient, so the order stands

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

    def test_a_resting_wall_is_still(self):
        # ADR-0020: with no default, the first resting pane by id shows and
        # stays, however the producers' rewrites interleave.
        state, shown = {}, set()
        for t in range(0, 600, 30):
            order = [("fleet", t % 7), ("home", (t + 3) % 7), ("weather", (t + 5) % 7)]
            pointer, state = decide(self.resting(order), T0 + timedelta(seconds=t), state)
            shown.add(pointer["pane"])
        self.assertEqual(shown, {"fleet"})

    def test_the_default_still_comes_first(self):
        panes = self.resting([("fleet", 0), ("home", 0), ("weather", 0)])
        pointer, _ = run(panes, default_pane="weather")
        ids = [r["id"] for r in rubric.explain(panes, T0, pointer, default_pane="weather")]
        self.assertEqual(ids, ["weather", "fleet", "home"])

    def test_other_classes_rank_by_arrival_not_created(self):
        a = pane("a-first", "attention", created=T0 - timedelta(minutes=1), ttl=240)
        b = pane("b-second", "attention", created=T0 - timedelta(minutes=2), ttl=240)
        _, state = run([a])
        pointer, _ = run([a, b], now=T0 + timedelta(seconds=5), state=state)
        self.assertEqual(pointer["pane"], "b-second")   # arrived last, though created first


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
        source = {"url": self.URL, "theme": "light", "screens": 1,
                  "viewport": [1920, 1080], "refresh_s": 300, "zoom": 2}
        pointer, _ = run([self.link(source=source)], link_panes=True)
        self.assertEqual(pointer["source"], {"url": self.URL, "theme": "light", "screens": 1,
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
            # A pane is one band (ADR-0020): screens is 1 or absent.
            ({"url": self.URL, "screens": 2}, "source.screens"),
            ({"url": self.URL, "screens": 4}, "source.screens"),
            ({"url": self.URL, "screens": 0}, "source.screens"),
            ({"url": self.URL, "screens": True}, "source.screens"),
            ({"url": self.URL, "viewport": [100, 720]}, "source.viewport"),
            ({"url": self.URL, "viewport": [1280]}, "source.viewport"),
            ({"url": self.URL, "refresh_s": 5}, "source.refresh_s"),
            ({"url": self.URL, "refresh_s": float("inf")}, "source.refresh_s"),
            ({"url": "https://ann:hunter2@x.test/"}, "carries credentials"),
            ({"url": "https://ann@x.test/"}, "carries credentials"),
            ({"url": "https://x.test/d?token=abc"}, "carries a secret (token)"),
            ({"url": "https://x.test/cb#access_token=abc"}, "carries a secret (access_token)"),
        ]
        for source, reason in bad:
            with self.subTest(source=source):
                pointer, state = run([self.link(source=source)], link_panes=True)
                self.assertEqual(pointer["fallback"], "briefing")
                self.assertIn(reason, state["skipped"]["pr-93"])

    def test_dwell_s_is_accepted_and_ignored(self):
        # Rotation is retired (ADR-0020): no dwell_s value can skip a pane.
        for dwell in (30, -1, float("inf"), "slow", True):
            with self.subTest(dwell=dwell):
                pointer, state = run([pane("a", dwell=dwell)])
                self.assertEqual((pointer["pane"], state["skipped"]), ("a", {}))
                self.assertNotIn("dwell_s", rubric.parse_manifest("a", pane("a", dwell=dwell)["manifest"]))

    def test_an_old_style_pane_is_unchanged(self):
        pointer, _ = run([pane("focus-x")], link_panes=True)
        self.assertEqual(pointer["url"], "http://pub.lan/viewport/panes/focus-x/pane.html")
        self.assertIsNone(pointer["source"])


if __name__ == "__main__":
    unittest.main()
