import json
import unittest
import urllib.parse

from fleet_producer import github
from fleet_producer.github import GitHubError, agent_prs


def answer(status, doc):
    calls = []

    def transport(url, headers):
        calls.append((url, headers))
        return status, json.dumps(doc).encode("utf-8") if not isinstance(doc, bytes) else doc
    transport.calls = calls
    return transport


ITEM = {"repository_url": "https://api.github.com/repos/lentago/brasenia", "number": 87,
        "title": "Fix the thing", "created_at": "2026-10-28T20:00:00Z", "draft": False}


class SearchTest(unittest.TestCase):

    def test_the_query_is_the_runner_apps_open_prs_anywhere(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(github.URL).query)
        self.assertEqual(query["q"], ["is:pr is:open author:app/lentago-claude-runner"])
        self.assertEqual(query["order"], ["asc"])
        self.assertNotIn("org:", github.URL)

    def test_items(self):
        t = answer(200, {"total_count": 1, "items": [ITEM, dict(ITEM, number=88, draft=True,
                                                                 repository_url="https://api.github.com/repos/cpitzi/music-curator")]})
        total, prs = agent_prs(t)
        self.assertEqual(total, 1)
        self.assertEqual([(p["repo"], p["number"], p["draft"]) for p in prs],
                         [("lentago/brasenia", 87, False), ("cpitzi/music-curator", 88, True)])
        self.assertEqual(prs[0]["created"].isoformat(), "2026-10-28T20:00:00+00:00")
        self.assertNotIn("Authorization", t.calls[0][1])

    def test_a_malformed_item_is_skipped(self):
        _, prs = agent_prs(answer(200, {"total_count": 2, "items": [ITEM, {"number": "x"}]}))
        self.assertEqual(len(prs), 1)

    def test_errors(self):
        with self.assertRaisesRegex(GitHubError, "HTTP 403"):
            agent_prs(answer(403, {"message": "rate limited"}))
        with self.assertRaisesRegex(GitHubError, "unexpected body"):
            agent_prs(answer(200, b"<html>"))

        def down(url, headers):
            raise OSError("no route")
        with self.assertRaisesRegex(GitHubError, "unreachable"):
            agent_prs(down)


if __name__ == "__main__":
    unittest.main()
