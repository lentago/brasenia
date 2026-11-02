"""A fake GitHub search: canned items and counts, answered by query."""

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 2, 23, 40, tzinfo=timezone.utc)     # 6:40 PM in New York (EST)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def item(repo, number, title, login="cpitzi", created_ago_min=60, merged_ago_min=None,
         closed_ago_min=None, draft=False):
    """One search item shaped as GitHub returns it for a pull request."""
    created = NOW - timedelta(minutes=created_ago_min)
    merged = NOW - timedelta(minutes=merged_ago_min) if merged_ago_min is not None else None
    if merged is not None and closed_ago_min is None:
        closed_ago_min = merged_ago_min
    closed = NOW - timedelta(minutes=closed_ago_min) if closed_ago_min is not None else None
    return {
        "repository_url": "https://api.github.com/repos/" + repo,
        "number": number,
        "title": title,
        "user": {"login": login},
        "state": "closed" if closed else "open",
        "draft": draft,
        "created_at": iso(created),
        "closed_at": iso(closed),
        "updated_at": iso(closed or created),
        "pull_request": {"merged_at": iso(merged)},
    }


class FakeSearch:
    """A transport: ``(status, body)`` for a search URL, recording each query."""

    def __init__(self, items=(), open_now=3, opened=12, merged=9):
        self.items = list(items)
        self.counts = {"is:open": open_now, "created:": opened, "merged:": merged}
        self.queries = []
        self.status = 200
        self.body = None
        self.error = None

    def __call__(self, url, headers):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        query = params["q"][0]
        self.queries.append((query, params.get("per_page", [""])[0], params.get("sort", [""])[0]))
        if self.error:
            raise self.error
        if self.body is not None:
            return self.status, self.body
        for marker, total in self.counts.items():
            if marker in query:
                return self.status, json.dumps({"total_count": total, "items": []}).encode()
        return self.status, json.dumps({"total_count": len(self.items), "items": self.items}).encode()


def event(repo, number, title, status, ago_min, who="cpitzi"):
    return {"repo": repo, "number": number, "title": title, "who": who, "status": status,
            "when": NOW - timedelta(minutes=ago_min)}
