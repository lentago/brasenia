import http.client
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from helpers import NOW, FakeSearch, item

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
        fake = FakeSearch([
            item("lentago/kalmia", 1, "older merge", created_ago_min=300, merged_ago_min=120),
            item("lentago/kalmia", 2, "newest open", created_ago_min=5),
            item("lentago/betula", 3, "middle close", created_ago_min=200, closed_ago_min=60),
        ])
        snap = github.snapshot(MIDNIGHT, transport=fake)
        self.assertEqual([e["number"] for e in snap["events"]], [2, 3, 1])
        self.assertEqual((snap["open"], snap["opened_today"], snap["merged_today"]), (3, 12, 9))
        self.assertEqual(fake.queries, [
            ("org:lentago is:pr", "50", "updated"),
            ("org:lentago is:pr is:open", "1", ""),
            ("org:lentago is:pr created:>=2026-11-02T05:00:00+00:00", "1", ""),
            ("org:lentago is:pr merged:>=2026-11-02T05:00:00+00:00", "1", ""),
        ])

    def test_scope(self):
        fake = FakeSearch()
        github.snapshot(MIDNIGHT, scope="user:cpitzi", transport=fake)
        self.assertTrue(all(q.startswith("user:cpitzi is:pr") for q, _, _ in fake.queries))

    def test_failures_raise(self):
        fake = FakeSearch()
        fake.status = 403
        with self.assertRaisesRegex(github.GitHubError, "HTTP 403"):
            github.snapshot(MIDNIGHT, transport=fake)
        fake = FakeSearch()
        fake.error = OSError("no route")
        with self.assertRaisesRegex(github.GitHubError, "unreachable"):
            github.snapshot(MIDNIGHT, transport=fake)
        fake = FakeSearch()
        fake.error = http.client.IncompleteRead(b"{")
        with self.assertRaisesRegex(github.GitHubError, "unreachable"):
            github.snapshot(MIDNIGHT, transport=fake)
        fake = FakeSearch()
        fake.body = b"<html>"
        with self.assertRaisesRegex(github.GitHubError, "unexpected body"):
            github.snapshot(MIDNIGHT, transport=fake)


if __name__ == "__main__":
    unittest.main()
