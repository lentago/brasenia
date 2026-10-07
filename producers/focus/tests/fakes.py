"""A fake GitHub (and pub.lan) transport for the focus producer tests."""

import json
import zlib

from focus_producer.github import API


class FakeTransport:
    """Serves canned JSON per URL with ETags, honouring If-None-Match.

    ``fail`` set to an int makes every GitHub request return that status
    (403 with an exhausted rate limit, 502, ...); set to ``"network"`` it
    raises OSError. ``calls`` records ``(url, headers)`` in order. Like the
    real unauthenticated API, every GitHub response, 304s included, spends
    one of ``remaining`` and reports it.
    """

    def __init__(self):
        self.routes = {}
        self.calls = []
        self.fail = None
        self.remaining = 60
        self.reset = 4_000_000_000

    def set(self, url, body, etag=None):
        self.routes[url] = (etag or '"%08x"' % zlib.crc32(json.dumps(body).encode()), json.dumps(body))

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url.startswith(API) and self.fail == "network":
            raise OSError("connection refused")
        limits = {}
        if url.startswith(API):
            self.remaining = max(0, self.remaining - 1)
            limits = {"x-ratelimit-remaining": str(self.remaining),
                      "x-ratelimit-reset": str(self.reset)}
        if url.startswith(API) and self.fail is not None:
            return self.fail, limits, b"{}"
        if url not in self.routes:
            return 404, limits, b'{"message": "Not Found"}'
        etag, body = self.routes[url]
        if headers.get("If-None-Match") == etag:
            return 304, dict(limits, etag=etag), b""
        return 200, dict(limits, etag=etag), body.encode()

    def github_calls(self):
        return [c for c in self.calls if c[0].startswith(API)]


def serve_repo(transport, repo, pulls=(), main_conclusion="success", main_runs=None):
    """Route the endpoints GitHub.repo() reads for ``repo``.

    ``pulls`` are dicts with number/title/author/sha and optional draft,
    checks (list of (status, conclusion)), reviews (list of (user, state)).
    """
    listing = []
    for pr in pulls:
        listing.append({
            "number": pr["number"],
            "title": pr["title"],
            "user": {"login": pr.get("author", "octocat")},
            "created_at": pr.get("created_at", "2026-10-07T10:00:00Z"),
            "draft": pr.get("draft", False),
            "head": {"sha": pr.get("sha", "abc%d" % pr["number"])},
            "requested_reviewers": pr.get("requested", []),
        })
        transport.set("%s/repos/%s/commits/%s/check-runs?per_page=100"
                      % (API, repo, pr.get("sha", "abc%d" % pr["number"])),
                      {"check_runs": [{"status": s, "conclusion": c}
                                      for s, c in pr.get("checks", [])]})
        transport.set("%s/repos/%s/pulls/%d/reviews?per_page=100" % (API, repo, pr["number"]),
                      [{"user": {"login": u}, "state": s} for u, s in pr.get("reviews", [])])
    transport.set("%s/repos/%s/pulls?state=open&per_page=100" % (API, repo), listing)
    runs = []
    if main_runs is not None:
        runs = [{"conclusion": c, "name": n, "updated_at": "2026-10-07T11:30:00Z"}
                for n, c in main_runs]
    elif main_conclusion:
        runs = [{"conclusion": main_conclusion, "name": "docs-check",
                 "updated_at": "2026-10-07T11:30:00Z"}]
    transport.set("%s/repos/%s/actions/runs?branch=main&event=push&status=completed&per_page=5"
                  % (API, repo), {"workflow_runs": runs})
