import unittest

from fakes import FakeTransport, serve_repo
from focus_producer.github import API, BUDGET_PER_HOUR, GitHub, GitHubError, check_state, review_decision

REPO = "lentago/brasenia"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.t = FakeTransport()
        self.clock = Clock()
        self.gh = GitHub(self.t, self.clock)
        serve_repo(self.t, REPO, [
            {"number": 7, "title": "Add focus producer", "author": "claude",
             "checks": [("completed", "success")], "reviews": [("cpitzi", "APPROVED")]},
        ])

    def test_fetch_shape(self):
        data, fetched = self.gh.repo(REPO)
        self.assertEqual(fetched, self.clock.t)
        self.assertEqual(data["main"]["conclusion"], "success")
        pr = data["pulls"][0]
        self.assertEqual((pr["number"], pr["author"], pr["checks"], pr["review"]),
                         (7, "claude", "passing", "approved"))
        for url, headers in self.t.calls:
            self.assertNotIn("Authorization", headers)

    def test_cached_until_hold_expires(self):
        self.gh.repo(REPO)
        n = len(self.t.calls)
        hold = self.gh.hold_s(REPO)
        self.clock.t += hold - 1
        self.gh.repo(REPO)
        self.assertEqual(len(self.t.calls), n)
        self.clock.t += 2
        self.gh.repo(REPO)
        self.assertGreater(len(self.t.calls), n)

    def test_hold_paces_to_the_hourly_budget(self):
        self.assertEqual(GitHub(self.t, self.clock, cache_s=5).cache_s, 60)
        self.gh.repo(REPO)  # 1 PR: pulls + runs + check-runs + reviews = 4 requests
        self.assertEqual(self.gh.hold_s(REPO), 3600 * 4 / BUDGET_PER_HOUR)
        self.assertEqual(self.gh.hold_s(REPO, active=3), 3 * 3600 * 4 / BUDGET_PER_HOUR)
        for active in (1, 2, 5):
            self.assertLessEqual(4 * 3600 / self.gh.hold_s(REPO, active) * active, BUDGET_PER_HOUR)
            self.assertGreaterEqual(self.gh.hold_s(REPO, active), 60)

    def test_low_budget_skips_refresh_without_spending(self):
        self.gh.repo(REPO)
        self.clock.t += 3600
        n = len(self.t.calls)
        self.gh._remaining = 3  # as the last response reported; the next refresh needs 4
        with self.assertRaises(GitHubError):
            self.gh.repo(REPO)
        self.assertEqual(len(self.t.calls), n)
        self.clock.t = self.t.reset + 1  # window reset: refresh resumes
        self.gh.repo(REPO)
        self.assertGreater(len(self.t.calls), n)

    def test_listing_that_reveals_an_unaffordable_fan_out_stops_before_spending(self):
        many = [{"number": n, "title": "PR %d" % n} for n in range(1, 6)]  # 5 PRs: 2 + 10 requests
        serve_repo(self.t, REPO, many)
        self.t.remaining = 7  # the listing leaves 6; the fan-out needs 11 more
        with self.assertRaises(GitHubError) as ctx:
            self.gh.repo(REPO)
        self.assertEqual(len(self.t.github_calls()), 1)  # only the listing was spent
        self.assertIn("5 open PRs", str(ctx.exception))
        self.assertEqual(self.gh._cost[REPO], 12)  # the next preflight knows the real cost
        self.clock.t = self.t.reset + 1
        self.t.remaining = 60
        data, _ = self.gh.repo(REPO)
        self.assertEqual(len(data["pulls"]), 5)

    def test_etag_reuse_after_cache_expiry(self):
        first, _ = self.gh.repo(REPO)
        n = len(self.t.calls)
        self.clock.t += self.gh.hold_s(REPO) + 1
        second, _ = self.gh.repo(REPO)
        refetch = self.t.calls[n:]
        self.assertEqual(len(refetch), n)
        self.assertTrue(all("If-None-Match" in h for _u, h in refetch))
        self.assertEqual(first, second)

    def test_changed_resource_is_refetched(self):
        self.gh.repo(REPO)
        self.clock.t += self.gh.hold_s(REPO) + 1
        serve_repo(self.t, REPO, [], main_conclusion="failure")
        data, _ = self.gh.repo(REPO)
        self.assertEqual(data["pulls"], [])
        self.assertEqual(data["main"]["conclusion"], "failure")

    def test_rate_limit_raises_and_blocks_until_reset(self):
        self.t.remaining = 1
        self.t.fail = 403
        with self.assertRaises(GitHubError):
            self.gh.repo(REPO)
        n = len(self.t.calls)
        with self.assertRaises(GitHubError):
            self.gh.repo(REPO)
        self.assertEqual(len(self.t.calls), n)

    def test_network_and_5xx_raise(self):
        for fail in ("network", 502):
            self.t.fail = fail
            with self.assertRaises(GitHubError):
                GitHub(self.t, self.clock).repo(REPO)

    def test_failure_keeps_last_good_etags(self):
        self.gh.repo(REPO)
        self.clock.t += self.gh.hold_s(REPO) + 1
        self.t.fail = 502
        with self.assertRaises(GitHubError):
            self.gh.repo(REPO)
        self.t.fail = None
        n = len(self.t.calls)
        self.gh.repo(REPO)
        self.assertTrue(all("If-None-Match" in h for _u, h in self.t.calls[n:]))

    def test_no_main_runs(self):
        serve_repo(self.t, "lentago/new", [], main_conclusion=None)
        data, _ = self.gh.repo("lentago/new")
        self.assertIsNone(data["main"])

    def test_main_skips_skipped_neutral_cancelled(self):
        serve_repo(self.t, "lentago/x", [], main_runs=[
            ("comment", "skipped"), ("ping", "neutral"), ("ci", "cancelled"),
            ("docs-check", "failure"), ("old", "success")])
        data, _ = self.gh.repo("lentago/x")
        self.assertEqual(data["main"]["conclusion"], "failure")
        self.assertEqual(data["main"]["name"], "docs-check")

    def test_main_none_when_only_ignored_runs(self):
        serve_repo(self.t, "lentago/x", [], main_runs=[("a", "skipped"), ("b", "cancelled")])
        data, _ = self.gh.repo("lentago/x")
        self.assertIsNone(data["main"])

    def test_main_is_one_request(self):
        serve_repo(self.t, "lentago/x", [], main_runs=[("a", "skipped"), ("b", "success")])
        self.gh.repo("lentago/x")
        self.assertEqual(sum("actions/runs" in u for u, _h in self.t.calls), 1)

    def test_urls(self):
        self.gh.repo(REPO)
        urls = [u for u, _h in self.t.calls]
        self.assertIn(API + "/repos/lentago/brasenia/actions/runs?branch=main&event=push&status=completed&per_page=5", urls)
        self.assertIn(API + "/repos/lentago/brasenia/pulls?state=open&per_page=100", urls)


class FoldTests(unittest.TestCase):
    def test_check_state(self):
        self.assertEqual(check_state([]), "none")
        self.assertEqual(check_state([{"status": "completed", "conclusion": "success"},
                                      {"status": "completed", "conclusion": "skipped"}]), "passing")
        self.assertEqual(check_state([{"status": "completed", "conclusion": "success"},
                                      {"status": "in_progress", "conclusion": None}]), "pending")
        self.assertEqual(check_state([{"status": "in_progress", "conclusion": None},
                                      {"status": "completed", "conclusion": "failure"}]), "failing")

    def test_review_decision(self):
        u = lambda login, state: {"user": {"login": login}, "state": state}  # noqa: E731
        self.assertEqual(review_decision([], []), "no review")
        self.assertEqual(review_decision([], [{"login": "x"}]), "review requested")
        self.assertEqual(review_decision([u("a", "APPROVED")], []), "approved")
        self.assertEqual(review_decision([u("a", "CHANGES_REQUESTED"), u("b", "APPROVED")], []),
                         "changes requested")
        # A later approval supersedes the same reviewer's change request; comments don't.
        self.assertEqual(review_decision([u("a", "CHANGES_REQUESTED"), u("a", "APPROVED"),
                                          u("a", "COMMENTED")], []), "approved")
        self.assertEqual(review_decision([u("a", "APPROVED"), u("a", "DISMISSED")], []), "no review")


if __name__ == "__main__":
    unittest.main()
