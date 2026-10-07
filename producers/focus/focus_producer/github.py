"""Unauthenticated GitHub REST client with ETag reuse and a per-repo cache.

Every lentago repo is public, so the producer reads GitHub without a token
and the viewport stays credential-free. The unauthenticated budget is 60
requests an hour per IP. Every request carries ``If-None-Match`` with the
stored ETag, but measured 2026-10-07, an unauthenticated 304 still spends
one request (GitHub exempts 304s only for authorized requests), so the
budget is kept by pacing instead:

* a refresh costs 2 + 2 × open PRs requests; each repo's data is cached for
  at least 60 s and, beyond that, long enough that all active repos together
  spend at most BUDGET_PER_HOUR requests an hour, and
* no refresh starts when the server says fewer requests remain than it
  will cost; the pane keeps its old data until the window resets.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "brasenia-focus-producer",
    "X-GitHub-Api-Version": "2022-11-28",
}
MIN_CACHE_S = 60.0
BUDGET_PER_HOUR = 50  # of the 60 unauthenticated requests; the rest is headroom
FIRST_COST = 2        # a repo's first refresh: pulls + main runs, before PRs are known


class GitHubError(Exception):
    """Any GitHub failure: network, rate limit, 5xx, or an unexpected body."""


def urllib_transport(url, headers, timeout=15):
    """GET ``url``; return ``(status, headers, body)``. Raises OSError on network failure.

    Non-2xx responses (304, 403, 5xx, ...) are returned, not raised, so the
    caller sees every status the same way. Header names are lower-cased.
    """
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _lower(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, _lower(err.headers), err.read()


def _lower(headers):
    return {k.lower(): v for k, v in (headers or {}).items()}


def parse_ts(value):
    """RFC 3339 timestamp → aware UTC datetime (3.9's fromisoformat lacks 'Z')."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError("timestamp has no offset: %r" % value)
    return ts.astimezone(timezone.utc)


class GitHub:
    """Fetches a repo's open PRs and ``main``'s latest completed run."""

    def __init__(self, transport=urllib_transport, clock=time.time, cache_s=MIN_CACHE_S):
        self.transport = transport
        self.clock = clock
        self.cache_s = max(cache_s, MIN_CACHE_S)
        self._etags = {}        # repo -> {url: (etag, parsed body)}
        self._cache = {}        # repo -> (fetched_at epoch, data)
        self._cost = {}         # repo -> requests its last refresh spent
        self._remaining = None  # x-ratelimit-remaining from the last response
        self._reset = 0.0       # x-ratelimit-reset, epoch seconds

    def hold_s(self, repo, active=1):
        """How long ``repo``'s data is reused, with ``active`` repos sharing the budget."""
        cost = self._cost.get(repo, FIRST_COST)
        return max(self.cache_s, 3600.0 * cost * max(active, 1) / BUDGET_PER_HOUR)

    def repo(self, repo, active=1):
        """Return ``(data, fetched_at)`` for ``repo``, from cache when fresh.

        ``data`` is ``{"pulls": [...], "main": {...} or None}``. ``active``
        is how many repos the producer is refreshing (they share the
        budget). Raises GitHubError on any failure; the caller keeps its
        previous pane.
        """
        now = self.clock()
        cached = self._cache.get(repo)
        if cached and now - cached[0] < self.hold_s(repo, active):
            return cached[1], cached[0]
        need = self._cost.get(repo, FIRST_COST)
        if self._remaining is not None and self._remaining < need and now < self._reset:
            raise GitHubError("%d requests left, need %d; window resets %s"
                              % (self._remaining, need, _hhmm_utc(self._reset)))

        old = self._etags.get(repo, {})
        used = {}
        get = lambda path: self._get(old, used, path)  # noqa: E731

        pulls = []
        for pr in get("/repos/%s/pulls?state=open&per_page=100" % repo):
            sha = pr["head"]["sha"]
            runs = get("/repos/%s/commits/%s/check-runs?per_page=100" % (repo, sha))
            reviews = get("/repos/%s/pulls/%d/reviews?per_page=100" % (repo, pr["number"]))
            pulls.append({
                "number": pr["number"],
                "title": pr["title"],
                "author": (pr.get("user") or {}).get("login", "?"),
                "created_at": pr["created_at"],
                "draft": bool(pr.get("draft")),
                "checks": check_state(runs.get("check_runs", [])),
                "review": review_decision(reviews, pr.get("requested_reviewers") or []),
            })
        runs = get("/repos/%s/actions/runs?branch=main&status=completed&per_page=1" % repo)
        latest = (runs.get("workflow_runs") or [None])[0]
        main = None
        if latest:
            main = {
                "conclusion": latest.get("conclusion") or "unknown",
                "name": latest.get("name") or "",
                "updated_at": latest.get("updated_at") or latest.get("created_at"),
            }

        # Keep only the ETags this fetch used, so superseded head SHAs don't pile up.
        self._etags[repo] = used
        self._cost[repo] = len(used)
        data = {"pulls": pulls, "main": main}
        self._cache[repo] = (now, data)
        return data, now

    def forget(self, repo):
        """Drop cached state for a repo whose pane is gone."""
        self._etags.pop(repo, None)
        self._cache.pop(repo, None)
        self._cost.pop(repo, None)

    def _get(self, old, used, path):
        url = API + path
        headers = dict(HEADERS)
        stored = old.get(url)
        if stored and stored[0]:
            headers["If-None-Match"] = stored[0]
        try:
            status, resp_headers, body = self.transport(url, headers)
        except OSError as err:
            raise GitHubError("network: %s" % err) from err
        self._track_budget(resp_headers)
        if status == 304 and stored:
            used[url] = stored
            return stored[1]
        if status == 200:
            try:
                parsed = json.loads(body)
            except ValueError as err:
                raise GitHubError("bad JSON from %s" % path) from err
            used[url] = (resp_headers.get("etag"), parsed)
            return parsed
        if status in (403, 429) and resp_headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError("rate limited (HTTP %d) on %s" % (status, path))
        raise GitHubError("HTTP %d on %s" % (status, path))

    def _track_budget(self, headers):
        try:
            self._remaining = int(headers["x-ratelimit-remaining"])
            self._reset = float(headers["x-ratelimit-reset"])
        except (KeyError, ValueError):
            pass


def check_state(check_runs):
    """Fold a commit's check runs into one of failing / pending / passing / none."""
    if not check_runs:
        return "none"
    state = "passing"
    for run in check_runs:
        if run.get("status") != "completed":
            state = "pending"
        elif run.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required",
                                       "startup_failure", "stale"):
            return "failing"
    return state


def review_decision(reviews, requested_reviewers):
    """Approximate GraphQL's reviewDecision from the REST reviews list.

    Each reviewer's latest APPROVED / CHANGES_REQUESTED / DISMISSED review
    counts; comments don't change a reviewer's standing.
    """
    latest = {}
    for review in reviews:
        state = review.get("state")
        login = (review.get("user") or {}).get("login")
        if login and state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[login] = state
    states = set(latest.values())
    if "CHANGES_REQUESTED" in states:
        return "changes requested"
    if "APPROVED" in states:
        return "approved"
    if requested_reviewers:
        return "review requested"
    return "no review"


def _hhmm_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%MZ")
