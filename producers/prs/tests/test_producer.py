import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from helpers import NOW, RESET, FakeGitHub, event, item, node

from prs_producer import github, producer
from prs_producer.github import GitHubError
from prs_producer.producer import Producer


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Client:
    """A stand-in for ``github.Client``: canned snapshots and states, recorded."""

    def __init__(self, token=True):
        self.authenticated = token
        self.calls = []           # (since, scope) of each snapshot
        self.state_calls = []     # the ids of each states query
        self.fail = False
        self.state_fail = False
        self.events = [event("lentago/kalmia", 276, "Start with Remote Control", "merged", 29)]
        self.rate = {"cost": 1, "remaining": 4000, "reset": NOW + timedelta(minutes=30)}
        self.answer = {}

    def snapshot(self, since, scope):
        self.calls.append((since, scope))
        if self.fail:
            raise GitHubError("search answered HTTP 403")
        return {"open": 3, "opened_today": 12, "merged_today": 9, "events": list(self.events)}

    def states(self, ids):
        self.state_calls.append(list(ids))
        if self.state_fail:
            raise GitHubError("GraphQL answered HTTP 502")
        return {i: self.answer[i] for i in ids if i in self.answer}, dict(self.rate)


class ProducerTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.pane = os.path.join(self.root, "viewport", "panes", "prs")
        self.clock, self.snap = Clock(), Client()
        self.producer = Producer(self.root, client=self.snap, clock=self.clock)

    def manifest(self):
        with open(os.path.join(self.pane, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def page(self):
        with open(os.path.join(self.pane, "pane.html"), encoding="utf-8") as fh:
            return fh.read()

    def test_writes_the_pane(self):
        self.producer.cycle()
        self.assertEqual(sorted(os.listdir(self.pane)), ["manifest.json", "pane.html"])
        m = self.manifest()
        self.assertEqual((m["schema"], m["class"], m["title"], m["ttl_minutes"], m["author"], m["origin"]),
                         (1, "ambient", "Pull requests", 10, "prs-producer@pub", "operator"))
        self.assertEqual(m["created"], "2026-11-02T23:40:00Z")
        self.assertIn("Start with Remote Control", self.page())

    def test_today_starts_at_local_midnight(self):
        self.producer.cycle()
        since, scope = self.snap.calls[0]
        self.assertEqual(since.isoformat(), "2026-11-02T00:00:00-05:00")
        self.assertEqual(scope, "org:lentago")

    def test_refresh_is_paced_but_the_pane_is_renewed(self):
        self.producer.cycle()
        self.clock.now = NOW + timedelta(seconds=producer.REFRESH_S - 1)
        self.producer.cycle()
        self.assertEqual(len(self.snap.calls), 1)
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:41:59Z")
        self.clock.now = NOW + timedelta(seconds=producer.REFRESH_S)
        self.producer.cycle()
        self.assertEqual(len(self.snap.calls), 2)

    def test_a_failed_refresh_keeps_the_last_list(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(minutes=5)
        self.producer.cycle()
        page = self.page()
        self.assertIn("Start with Remote Control", page)
        self.assertIn("GitHub unavailable, last tried 6:45 PM", page)
        self.assertIn("GitHub search · as of 6:40 PM", page)
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:45:00Z")

    def test_recovery_clears_the_warning(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(minutes=3)
        self.producer.cycle()
        self.snap.fail = False
        self.clock.now = NOW + timedelta(minutes=6)
        self.producer.cycle()
        self.assertNotIn("GitHub unavailable", self.page())

    def test_nothing_is_written_before_the_first_good_search(self):
        self.snap.fail = True
        self.producer.cycle()
        self.assertFalse(os.path.exists(self.pane))

    def test_stale_data_is_left_to_its_ttl(self):
        self.producer.cycle()
        self.snap.fail = True
        self.clock.now = NOW + timedelta(seconds=producer.STALE_S + 60)
        self.producer.cycle()
        self.assertEqual(self.manifest()["created"], "2026-11-02T23:40:00Z")

    def test_someone_elses_pane_is_left_alone(self):
        os.makedirs(self.pane)
        with open(os.path.join(self.pane, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"author": "someone@else"}, fh)
        self.producer.cycle()
        self.assertEqual(self.manifest(), {"author": "someone@else"})
        self.assertFalse(os.path.exists(os.path.join(self.pane, "pane.html")))

    def staging(self):
        return os.path.join(self.root, "viewport", "staging")

    def test_a_new_pane_appears_in_one_rename(self):
        renames = []
        real = os.rename

        def spy(src, dst):
            bus = os.path.join(self.root, "viewport")
            renames.append((os.path.relpath(os.path.dirname(src), bus), os.path.relpath(dst, bus)))
            self.assertEqual(sorted(os.listdir(src)), ["manifest.json", "pane.html"])
            return real(src, dst)

        with mock.patch.object(producer.os, "rename", spy):
            self.producer.cycle()
        self.assertEqual(renames, [("staging", os.path.join("panes", "prs"))])
        self.assertEqual(os.listdir(self.staging()), [])
        self.assertEqual(self.manifest()["author"], "prs-producer@pub")

    def appears_first(self, author):
        """Patch the create rename so that ``author``'s pane lands at the
        target just before it: the race of #51."""
        real = os.rename

        def racer(src, dst):
            if dst == self.pane:
                os.makedirs(dst)
                with open(os.path.join(dst, "pane.html"), "w") as fh:
                    fh.write("<p>first</p>")
                with open(os.path.join(dst, "manifest.json"), "w") as fh:
                    json.dump({"author": author, "title": "first"}, fh)
            return real(src, dst)

        return mock.patch.object(producer.os, "rename", racer)

    def test_a_cycle_that_loses_the_race_leaves_the_winner_alone(self):
        with self.appears_first("someone@else"):
            self.producer.cycle()
        self.assertEqual(self.manifest(), {"author": "someone@else", "title": "first"})
        self.assertEqual(self.page(), "<p>first</p>")
        self.assertEqual(os.listdir(self.staging()), [])

    def test_losing_the_race_to_itself_updates_in_place(self):
        with self.appears_first("prs-producer@pub"):
            self.producer.cycle()
        self.assertEqual(self.manifest()["title"], "Pull requests")
        self.assertIn("Start with Remote Control", self.page())
        self.assertEqual(sorted(os.listdir(self.pane)), ["manifest.json", "pane.html"])
        self.assertEqual(os.listdir(self.staging()), [])

    def test_an_existing_pane_is_rewritten_file_by_file_manifest_last(self):
        self.producer.cycle()
        order = []
        real = os.replace

        def spy(src, dst):
            order.append((os.path.basename(src), os.path.basename(dst)))
            return real(src, dst)

        self.clock.now = NOW + timedelta(seconds=30)
        with mock.patch.object(producer.os, "replace", spy):
            self.producer.cycle()
        self.assertEqual(order, [("pane.html.partial", "pane.html"),
                                 ("manifest.json.partial", "manifest.json")])


class StateTest(unittest.TestCase):
    """The open rows' state: read with the token, inside ADR-0021's budget (#137)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.pane = os.path.join(self.root, "viewport", "panes", "prs")
        self.clock, self.client = Clock(), Client()
        self.client.events = [
            event("lentago/kalmia", 300, "Armed one", "open", 5),
            event("lentago/kalmia", 299, "A draft", "draft", 6),
            event("lentago/betula", 12, "Merged one", "merged", 7),
            event("lentago/drosera", 41, "Unreviewed one", "open", 8, who="bullpen"),
        ]
        self.client.answer = {
            "PR_kalmia_300": {"checks": "pending", "armed": True, "reviewed": True},
            "PR_drosera_41": {"checks": "passing", "armed": False, "reviewed": False},
        }
        self.producer = Producer(self.root, client=self.client, clock=self.clock)

    def page(self):
        with open(os.path.join(self.pane, "pane.html"), encoding="utf-8") as fh:
            return fh.read()

    def at(self, **delta):
        self.clock.now = NOW + timedelta(**delta)
        self.producer.cycle()

    def test_open_rows_show_what_they_wait_on(self):
        self.producer.cycle()
        self.assertEqual(self.client.state_calls, [["PR_kalmia_300", "PR_drosera_41"]])
        page = self.page()
        self.assertIn(">armed</span>", page)
        self.assertIn(">awaiting review</span>", page)
        self.assertNotIn(">bullpen<", page)          # the state takes the author's place
        self.assertIn("GitHub search · as of 6:40 PM</div>", page)

    def test_only_the_rows_on_the_pane_are_asked_for(self):
        self.client.events = [event("lentago/kalmia", n, "PR %d" % n, "open", n) for n in range(1, 15)]
        self.producer.cycle()
        self.assertEqual(self.client.state_calls, [["PR_kalmia_%d" % n for n in range(1, 11)]])

    def test_no_token_no_state(self):
        self.client.authenticated = False
        self.producer.cycle()
        self.assertEqual(self.client.state_calls, [])
        page = self.page()
        self.assertIn(">bullpen<", page)
        self.assertIn("GitHub search · as of 6:40 PM · no GitHub token", page)

    def test_state_is_read_once_per_refresh(self):
        self.producer.cycle()
        self.at(seconds=producer.REFRESH_S - 1)
        self.assertEqual(len(self.client.state_calls), 1)
        self.at(seconds=producer.REFRESH_S)
        self.assertEqual(len(self.client.state_calls), 2)

    def test_a_failed_state_query_keeps_the_last_state_until_it_is_stale(self):
        self.producer.cycle()
        self.client.state_fail = True
        self.at(minutes=10)
        self.assertIn(">armed</span>", self.page())
        self.at(seconds=producer.STALE_S + 1)
        page = self.page()
        self.assertNotIn(">armed</span>", page)
        self.assertIn(">bullpen<", page)

    def test_a_failed_search_reads_no_state(self):
        self.client.fail = True
        self.producer.cycle()
        self.assertEqual(self.client.state_calls, [])

    def test_a_low_budget_pauses_state_until_the_reset(self):
        self.client.rate = {"cost": 1, "remaining": 999, "reset": NOW + timedelta(minutes=10)}
        with self.assertLogs("prs_producer.producer", "WARNING"):
            self.producer.cycle()
        self.assertIn("· PR state paused, rate limit low", self.page())
        self.assertIn(">armed</span>", self.page())   # the state just read still shows
        self.client.rate = {"cost": 1, "remaining": 4000, "reset": NOW + timedelta(minutes=30)}
        self.at(minutes=4)
        self.at(minutes=8)
        self.assertEqual(len(self.client.state_calls), 1)
        self.at(minutes=10)
        self.assertEqual(len(self.client.state_calls), 2)
        self.assertNotIn("paused", self.page())

    def test_the_hour_is_capped_at_the_budget(self):
        self.client.rate = {"cost": 80, "remaining": 4000, "reset": NOW + timedelta(minutes=30)}
        for minute in range(0, 20, 2):
            self.at(minutes=minute)
        self.assertEqual(len(self.client.state_calls), 3)    # 3 × 80 ≥ 200: no fourth
        self.at(minutes=60)
        self.assertEqual(len(self.client.state_calls), 4)    # the first has left the window

    def test_a_refused_token_drops_the_state_column(self):
        fake = FakeGitHub([item("lentago/drosera", 41, "Unreviewed one", login="cpitzi", created_ago_min=8)],
                          nodes=[node("PR_drosera_41")], token="good")
        client = github.Client("good", transport=fake)
        prod = Producer(self.root, client=client, clock=self.clock)
        prod.cycle()
        self.assertIn(">awaiting review</span>", self.page())
        fake.token = "rotated"                       # the token in hand is now refused
        self.clock.now = NOW + timedelta(seconds=producer.REFRESH_S)
        with self.assertLogs("prs_producer.github", "WARNING"):
            prod.cycle()
        page = self.page()
        self.assertNotIn("awaiting review", page)
        self.assertIn(">cpitzi<", page)
        self.assertIn("· no GitHub token", page)
        self.assertEqual(len(fake.graphql), 1)       # no GraphQL query without a token


if __name__ == "__main__":
    unittest.main()
