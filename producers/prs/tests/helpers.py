"""A fake GitHub: canned search items and counts, answered by query, and
canned GraphQL pull-request nodes, answered by node id."""

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 2, 23, 40, tzinfo=timezone.utc)     # 6:40 PM in New York (EST)
RESET = int((NOW + timedelta(minutes=30)).timestamp())


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
        "node_id": "PR_%s_%d" % (repo.split("/")[-1], number),
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


CI_REVIEW = "<!-- claude-review run=1 model=haiku -->\n## Review (haiku, claude-review.yml)\n\nNo major problems."
SOFT_FAIL = ("<!-- claude-review run=2 model=haiku -->\n⚠️ The automated Claude review could not "
             "complete this run")


def comment(body, login="github-actions", association="CONTRIBUTOR"):
    return {"author": {"login": login}, "authorAssociation": association, "body": body}


def node(node_id, checks="SUCCESS", armed=False, comments=(), labels=()):
    """One GraphQL PullRequest node, shaped as the states query asks for it."""
    return {
        "id": node_id,
        "autoMergeRequest": {"enabledAt": iso(NOW)} if armed else None,
        "labels": {"nodes": [{"name": name} for name in labels]},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": checks} if checks else None}}]},
        "comments": {"nodes": list(comments)},
    }


class FakeGitHub:
    """A transport: ``(status, body, headers)`` for a search URL or a GraphQL
    POST, recording each request.

    ``token`` is the one GitHub accepts; a request carrying another answers 401.
    """

    def __init__(self, items=(), open_now=3, opened=12, merged=9, nodes=(), token="good"):
        self.items = list(items)
        self.counts = {"is:open": open_now, "created:": opened, "merged:": merged}
        self.nodes = {n["id"]: n for n in nodes}
        self.token = token
        self.queries = []          # (query, per_page, sort) of each search
        self.graphql = []          # the ids of each GraphQL query
        self.auth = []             # the Authorization header of each request, or None
        self.status = 200          # for every search
        self.body = None           # for every search, in place of the canned answer
        self.error = None          # raised by every request
        self.graphql_status = 200
        self.graphql_body = None
        self.cost, self.remaining = 1, 4321

    def __call__(self, url, headers, data=None):
        auth = headers.get("Authorization")
        self.auth.append(auth)
        if self.error:
            raise self.error
        if auth is not None and auth != "Bearer %s" % self.token:
            return 401, b'{"message": "Bad credentials"}', {}
        if data is not None:
            return self._graphql(url, auth, json.loads(data.decode()))
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        query = params["q"][0]
        self.queries.append((query, params.get("per_page", [""])[0], params.get("sort", [""])[0]))
        if self.body is not None:
            return self.status, self.body, {}
        for marker, total in self.counts.items():
            if marker in query:
                return self.status, json.dumps({"total_count": total, "items": []}).encode(), {}
        return self.status, json.dumps({"total_count": len(self.items), "items": self.items}).encode(), {}

    def _graphql(self, url, auth, payload):
        assert url == "https://api.github.com/graphql", url
        ids = payload["variables"]["ids"]
        self.graphql.append(ids)
        if auth is None:
            return 401, b'{"message": "This endpoint requires you to be authenticated."}', {}
        if self.graphql_body is not None:
            return self.graphql_status, self.graphql_body, {}
        doc = {"data": {"rateLimit": {"cost": self.cost, "remaining": self.remaining,
                                      "resetAt": iso(NOW)},
                        "nodes": [self.nodes.get(i) for i in ids]}}
        headers = {"x-ratelimit-remaining": str(self.remaining), "x-ratelimit-reset": str(RESET)}
        return self.graphql_status, json.dumps(doc).encode(), headers


def event(repo, number, title, status, ago_min, who="cpitzi"):
    return {"id": "PR_%s_%d" % (repo.split("/")[-1], number), "repo": repo, "number": number,
            "title": title, "who": who, "status": status, "when": NOW - timedelta(minutes=ago_min)}
