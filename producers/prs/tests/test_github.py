import http.client
import json
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from helpers import CI_REVIEW, NOW, RESET, SOFT_FAIL, FakeGitHub, comment, item, node

from prs_producer import github

MIDNIGHT = datetime(2026, 11, 2, tzinfo=ZoneInfo("America/New_York"))    # 05:00Z


class ParseTest(unittest.TestCase):

    def test_statuses_and_event_times(self):
        merged = github.parse(item("lentago/kalmia", 276, "Merged", created_ago_min=90, merged_ago_min=29))
        self.assertEqual((merged["status"], merged["when"]), ("merged", NOW.replace(minute=11)))
        closed = github.parse(item("lentago/betula", 5, "Closed", created_ago_min=90, closed_ago_min=10))
        self.assertEqual((closed["status"], closed["when"]), ("closed", NOW.replace(minute=30)))
        opened = github.parse(item("lentago/drosera", 7, "Open", created_ago_min=15))
        self.assertEqual((opened["status"], opened["when"]), ("open", NOW.replace(minute=25)))
        draft = github.parse(item("lentago/drosera", 8, "Draft", created_ago_min=15, draft=True))
        self.assertEqual(draft["status"], "draft")
        self.assertEqual((merged["repo"], merged["number"], merged["title"]), ("lentago/kalmia", 276, "Merged"))
        self.assertEqual(merged["id"], "PR_kalmia_276")

    def test_who(self):
        self.assertEqual(github.who("lentago-claude-runner[bot]"), "bullpen")
        self.assertEqual(github.who("dependabot[bot]"), "dependabot")
        self.assertEqual(github.who("cpitzi"), "cpitzi")

    def test_malformed_items_are_skipped(self):
        self.assertIsNone(github.parse({"number": 1}))
        no_pr = item("lentago/kalmia", 1, "An issue")
        del no_pr["pull_request"]
        self.assertIsNone(github.parse(no_pr))


class SnapshotTest(unittest.TestCase):

    def test_four_searches_and_newest_first(self):
        fake = FakeGitHub([
            item("lentago/kalmia", 1, "older merge", created_ago_min=300, merged_ago_min=120),
            item("lentago/kalmia", 2, "newest open", created_ago_min=5),
            item("lentago/betula", 3, "middle close", created_ago_min=200, closed_ago_min=60),
        ])
        snap = github.Client(transport=fake).snapshot(MIDNIGHT)
        self.assertEqual([e["number"] for e in snap["events"]], [2, 3, 1])
        self.assertEqual((snap["open"], snap["opened_today"], snap["merged_today"]), (3, 12, 9))
        self.assertEqual(fake.queries, [
            ("org:lentago is:pr", "50", "updated"),
            ("org:lentago is:pr is:open", "1", ""),
            ("org:lentago is:pr created:>=2026-11-02T05:00:00+00:00", "1", ""),
            ("org:lentago is:pr merged:>=2026-11-02T05:00:00+00:00", "1", ""),
        ])

    def test_scope(self):
        fake = FakeGitHub()
        github.Client(transport=fake).snapshot(MIDNIGHT, scope="user:cpitzi")
        self.assertTrue(all(q.startswith("user:cpitzi is:pr") for q, _, _ in fake.queries))

    def test_failures_raise(self):
        def snapshot(fake):
            return github.Client(transport=fake).snapshot(MIDNIGHT)

        fake = FakeGitHub()
        fake.status = 403
        with self.assertRaisesRegex(github.GitHubError, "HTTP 403"):
            snapshot(fake)
        fake = FakeGitHub()
        fake.error = OSError("no route")
        with self.assertRaisesRegex(github.GitHubError, "unreachable"):
            snapshot(fake)
        fake = FakeGitHub()
        fake.error = http.client.IncompleteRead(b"{")
        with self.assertRaisesRegex(github.GitHubError, "unreachable"):
            snapshot(fake)
        fake = FakeGitHub()
        fake.body = b"<html>"
        with self.assertRaisesRegex(github.GitHubError, "unexpected body"):
            snapshot(fake)


class TokenTest(unittest.TestCase):

    def test_anonymous_sends_no_authorization(self):
        fake = FakeGitHub()
        client = github.Client(transport=fake)
        client.snapshot(MIDNIGHT)
        self.assertFalse(client.authenticated)
        self.assertEqual(set(fake.auth), {None})

    def test_the_token_goes_on_every_search(self):
        fake = FakeGitHub()
        github.Client("good", transport=fake).snapshot(MIDNIGHT)
        self.assertEqual(fake.auth, ["Bearer good"] * 4)

    def test_a_refused_token_is_dropped_once_and_the_search_repeated_without_it(self):
        fake = FakeGitHub(token="good")
        client = github.Client("expired", transport=fake)
        with self.assertLogs("prs_producer.github", "WARNING") as logs:
            snap = client.snapshot(MIDNIGHT)
        self.assertEqual(snap["open"], 3)
        self.assertFalse(client.authenticated)
        self.assertEqual(fake.auth, ["Bearer expired", None, None, None, None])
        self.assertEqual(len(logs.records), 1)
        self.assertIn("HTTP 401", logs.output[0])
        self.assertNotIn("expired", logs.output[0])

    def test_read_token(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "github-token")
        self.assertIsNone(github.read_token(None))
        self.assertIsNone(github.read_token(path))            # missing
        with open(path, "w") as fh:
            fh.write("")
        self.assertIsNone(github.read_token(path))            # empty, as the role seeds it
        with open(path, "w") as fh:
            fh.write("github_pat_x\n")
        self.assertEqual(github.read_token(path), "github_pat_x")


class StatesTest(unittest.TestCase):

    def states(self, *nodes, ids=None):
        fake = FakeGitHub(nodes=nodes)
        client = github.Client("good", transport=fake)
        states, rate = client.states(ids or [n["id"] for n in nodes])
        return states, rate, fake

    def test_one_query_for_the_ids(self):
        states, rate, fake = self.states(node("PR_a_1"), node("PR_b_2"))
        self.assertEqual(fake.graphql, [["PR_a_1", "PR_b_2"]])
        self.assertEqual(fake.auth, ["Bearer good"])
        self.assertEqual(sorted(states), ["PR_a_1", "PR_b_2"])
        self.assertEqual(rate, {"cost": 1, "remaining": 4321,
                                "reset": datetime.fromtimestamp(RESET, NOW.tzinfo)})

    def test_checks_and_auto_merge(self):
        states, _, _ = self.states(node("p", "SUCCESS", armed=True), node("f", "FAILURE"),
                                   node("e", "ERROR"), node("r", "PENDING"), node("x", "EXPECTED"),
                                   node("n", None))
        self.assertEqual({k: v["checks"] for k, v in states.items()},
                         {"p": "passing", "f": "failing", "e": "failing", "r": "pending",
                          "x": "pending", "n": None})
        self.assertEqual({k: v["armed"] for k, v in states.items() if v["armed"]}, {"p": True})

    def test_review_state(self):
        states, _, _ = self.states(
            node("ci", comments=[comment("### terraform plan"), comment(CI_REVIEW)]),
            node("local", comments=[comment("## Review (Haiku, local)\n\nFine.", "cpitzi", "MEMBER")]),
            node("bold", comments=[comment("**Review (Haiku, local)**", "cpitzi", "OWNER")]),
            node("soft", comments=[comment(SOFT_FAIL)]),
            node("triage", comments=[comment("**Review triage** (two findings)", "cpitzi", "MEMBER")]),
            node("outsider", comments=[comment("## Review (mine)", "stranger", "NONE")]),
            node("again", comments=[comment(CI_REVIEW)], labels=["re-review"]),
            node("sonnet", comments=[comment(CI_REVIEW)], labels=["review:sonnet"]),
            node("none"),
        )
        self.assertEqual(sorted(k for k, v in states.items() if v["reviewed"]), ["bold", "ci", "local"])

    def test_a_review_in_the_middle_of_a_busy_pr_is_found_from_either_end(self):
        chatter = [comment("### terraform plan")] * 60
        states, _, _ = self.states(node("early", comments=[comment(CI_REVIEW)] + chatter),
                                   node("late", comments=chatter + [comment(CI_REVIEW)]),
                                   node("buried", comments=chatter + [comment(CI_REVIEW)] + chatter))
        self.assertEqual({k: v["reviewed"] for k, v in states.items()},
                         {"early": True, "late": True, "buried": False})

    def test_unresolved_nodes_are_left_out(self):
        fake = FakeGitHub(nodes=[node("PR_a_1")])
        states, _ = github.Client("good", transport=fake).states(["PR_a_1", "PR_gone_9"])
        self.assertEqual(list(states), ["PR_a_1"])

    def test_no_token_no_query(self):
        fake = FakeGitHub(nodes=[node("PR_a_1")])
        self.assertEqual(github.Client(transport=fake).states(["PR_a_1"]), ({}, None))
        self.assertEqual(fake.graphql, [])

    def test_a_refused_token_ends_the_query_without_retrying(self):
        fake = FakeGitHub(nodes=[node("PR_a_1")], token="good")
        client = github.Client("revoked", transport=fake)
        with self.assertLogs("prs_producer.github", "WARNING"):
            self.assertEqual(client.states(["PR_a_1"]), ({}, None))
        self.assertFalse(client.authenticated)
        self.assertEqual(fake.auth, ["Bearer revoked"])

    def test_failures_raise(self):
        fake = FakeGitHub(nodes=[node("a")])
        fake.graphql_status = 502
        with self.assertRaisesRegex(github.GitHubError, "GraphQL answered HTTP 502"):
            github.Client("good", transport=fake).states(["a"])
        for body in (b"<html>", json.dumps({"errors": [{"type": "RATE_LIMITED"}]}).encode(),
                     json.dumps({"data": {"nodes": None}}).encode()):
            fake = FakeGitHub(nodes=[node("a")])
            fake.graphql_body = body
            with self.assertRaisesRegex(github.GitHubError, "unexpected body"):
                github.Client("good", transport=fake).states(["a"])

    def test_rate_from_the_body_when_headers_are_missing(self):
        fake = FakeGitHub(nodes=[node("a")])
        fake.graphql_body = json.dumps({"data": {
            "rateLimit": {"cost": 2, "remaining": 900, "resetAt": "2026-11-03T00:10:00Z"},
            "nodes": [node("a")]}}).encode()
        _, rate = github.Client("good", transport=fake).states(["a"])
        self.assertEqual((rate["cost"], rate["remaining"], rate["reset"].isoformat()),
                         (2, 900, "2026-11-03T00:10:00+00:00"))


if __name__ == "__main__":
    unittest.main()
