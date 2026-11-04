"""The fleet's pull requests from GitHub: the search API, plus each open
row's state from GraphQL when pub's token is present (ADR-0021).

Every ``lentago`` repository is public, so search without a token sees the
whole org. One refresh is four searches:

- the running list: the 50 most recently updated PRs. Each one's event time
  (merged, closed or opened) is never later than its ``updated_at``, so the
  newest events are among them unless more than 50 PRs were touched since
  without an event (comments, pushes);
- three counts, read from ``total_count`` with ``per_page=1``: open now,
  opened since local midnight, merged since local midnight.

Search results carry no check state, auto-merge or review. With a token,
one GraphQL query per refresh reads them for the open rows on the pane
(``states``, brasenia#137). GraphQL refuses anonymous callers, so without a
token there is no such query and the pane keeps the token-less view.

The token is sent on every read, search included (ADR-0021). When GitHub
answers 401, the token is dropped for the rest of the run, logged once, and
the request is repeated anonymously.
"""

import http.client
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_SCOPE = "org:lentago"
LIST_SIZE = 50
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "brasenia-prs-producer",
    "X-GitHub-Api-Version": "2022-11-28",
}
ENDPOINT = "https://api.github.com/search/issues?"
GRAPHQL = "https://api.github.com/graphql"

# Logins that read better by role than by name; any other "[bot]" suffix is dropped.
ALIASES = {
    "lentago-claude-runner[bot]": "bullpen",
}

# One query for up to ten open PRs. GitHub prices it at one point: four
# connections under each of ten nodes is 40 requests, under the 100 that make
# a point. ``rateLimit`` costs nothing and reports what this query cost.
# Comments are read from both ends, the first 50 and the last 50, so a review
# posted at opening and one posted after a re-review are both seen on a busy
# PR; only a review with more than 50 comments on either side of it is missed.
STATES_QUERY = """
query($ids: [ID!]!) {
  rateLimit { cost remaining resetAt }
  nodes(ids: $ids) {
    ... on PullRequest {
      id
      autoMergeRequest { enabledAt }
      labels(first: 20) { nodes { name } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      early: comments(first: 50) { nodes { author { login } authorAssociation body } }
      late: comments(last: 50) { nodes { author { login } authorAssociation body } }
    }
  }
}
"""

CHECKS = {"SUCCESS": "passing", "FAILURE": "failing", "ERROR": "failing",
          "PENDING": "pending", "EXPECTED": "pending"}
# A label that asks claude-review.yml for a fresh review; the caller removes
# it after the run, so while it is on the PR a review is still to come.
REVIEW_LABELS = {"re-review", "review:sonnet"}
# A review comment opens with a "Review (" heading: "## Review (haiku,
# claude-review.yml)" after the CI reviewer's hidden marker, or "Review
# (Haiku, local)" where a repo has no caller (.github ADR-0013). The CI
# reviewer's soft-fail notice ("could not complete") does not, and is not a
# review.
REVIEW_HEADING = re.compile(r"\A\s*(?:<!--.*?-->\s*)?[#*\s]*Review \(", re.S)
# Who may post a review: the Actions bot, or someone with a hand in the repo.
# Every repo is public, so anyone else's "Review (" comment is not counted.
REVIEWERS = {"github-actions"}
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}

log = logging.getLogger(__name__)


class GitHubError(Exception):
    """Any GitHub failure: network, rate limit, 5xx, or an unexpected body."""


def urllib_transport(url, headers, data=None, timeout=15):
    """GET ``url``, or POST ``data``; return ``(status, body, headers)`` with
    lower-cased header names. Raises OSError on network failure."""
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as err:
        return err.code, err.read(), {k.lower(): v for k, v in err.headers.items()}


def read_token(path):
    """The token in ``path``, or None when there is no path, no file or an empty one."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def search_url(query, per_page, sort=None):
    params = {"q": query, "per_page": per_page}
    if sort:
        params.update({"sort": sort, "order": "desc"})
    return ENDPOINT + urllib.parse.urlencode(params)


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def who(login):
    """A short name for the author: the runner App is "bullpen", "[bot]" is dropped."""
    if login in ALIASES:
        return ALIASES[login]
    return login[:-len("[bot]")] if login.endswith("[bot]") else login


def parse(item):
    """One search item as ``{"id", "repo", "number", "title", "who", "status", "when"}``.

    ``status`` is ``merged``, ``closed`` (without merging), ``draft`` or
    ``open``; ``when`` is the time of that event: merged, closed or opened.
    ``id`` is the PR's GraphQL node id, which ``states`` takes.
    Returns None for an item that is not a well-formed pull request.
    """
    try:
        pr = item["pull_request"]
        created = _ts(item["created_at"])
        merged = _ts(pr.get("merged_at"))
        if item["state"] == "closed":
            status, when = ("merged", merged) if merged else ("closed", _ts(item["closed_at"]) or created)
        else:
            status, when = ("draft" if item.get("draft") is True else "open"), created
        return {
            "id": item.get("node_id"),
            "repo": item["repository_url"].rsplit("/repos/", 1)[1],
            "number": int(item["number"]),
            "title": str(item["title"]),
            "who": who(str(item["user"]["login"])),
            "status": status,
            "when": when,
        }
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def reviewed(node):
    """True when a review has posted and no fresh one has been asked for (.github ADR-0013)."""
    labels = {(lb or {}).get("name") for lb in (node.get("labels") or {}).get("nodes") or []}
    if labels & REVIEW_LABELS:
        return False
    comments = [c for part in ("early", "late") for c in (node.get(part) or {}).get("nodes") or []]
    for comment in comments:
        comment = comment or {}
        login = (comment.get("author") or {}).get("login")
        if login not in REVIEWERS and comment.get("authorAssociation") not in TRUSTED:
            continue
        if REVIEW_HEADING.match(comment.get("body") or ""):
            return True
    return False


def parse_state(node):
    """One GraphQL PullRequest as ``{"checks", "armed", "reviewed"}``.

    ``checks`` is ``passing``, ``failing``, ``pending`` or None (no checks
    on the head commit).
    """
    commits = (node.get("commits") or {}).get("nodes") or []
    rollup = ((commits[-1] or {}).get("commit") or {}).get("statusCheckRollup") if commits else None
    return {
        "checks": CHECKS.get((rollup or {}).get("state")),
        "armed": node.get("autoMergeRequest") is not None,
        "reviewed": reviewed(node),
    }


class Client:
    """GitHub reads, with pub's token when it has one."""

    def __init__(self, token=None, transport=urllib_transport):
        self.token = token or None
        self.transport = transport

    @property
    def authenticated(self):
        return self.token is not None

    def _call(self, url, data=None):
        """``(status, body, headers)``. A 401 drops the token (logged once);
        a GET is then repeated without it, while a GraphQL POST, which has
        no anonymous form, returns the 401. Raises GitHubError when GitHub
        can't be reached."""
        while True:
            headers = dict(HEADERS)
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            if data is not None:
                headers["Content-Type"] = "application/json"
            try:
                status, body, resp_headers = self.transport(url, headers, data)
            except (OSError, http.client.HTTPException) as err:  # a truncated body is not an OSError
                raise GitHubError("unreachable (%s)" % err) from None
            if status == 401 and self.token:
                log.warning("GitHub refused the token (HTTP 401); reading without it for the rest "
                            "of this run")
                self.token = None
                if data is None:
                    continue
            return status, body, resp_headers

    def search(self, query, per_page, sort=None):
        """``(total_count, items)`` for one search, or GitHubError."""
        status, body, _ = self._call(search_url(query, per_page, sort))
        if status != 200:
            raise GitHubError("search answered HTTP %s" % status)
        try:
            doc = json.loads(body.decode("utf-8"))
            items = doc["items"]
            total = int(doc["total_count"])
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            raise GitHubError("search returned an unexpected body") from None
        return total, items if isinstance(items, list) else []

    def snapshot(self, since, scope=DEFAULT_SCOPE):
        """Counts and the running list, or GitHubError if any of the four searches fails.

        ``since`` is local midnight as an aware datetime; "today" counts start there.
        Returns ``{"open", "opened_today", "merged_today", "events"}``, with
        ``events`` newest first.
        """
        base = "%s is:pr" % scope
        day = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        _, items = self.search(base, LIST_SIZE, sort="updated")
        open_now, _ = self.search(base + " is:open", 1)
        opened, _ = self.search("%s created:>=%s" % (base, day), 1)
        merged, _ = self.search("%s merged:>=%s" % (base, day), 1)
        events = [e for e in (parse(i) for i in items) if e is not None and e["when"] is not None]
        events.sort(key=lambda e: e["when"], reverse=True)
        return {"open": open_now, "opened_today": opened, "merged_today": merged, "events": events}

    def states(self, ids):
        """``(states, rate)`` for the PRs with these node ids, or GitHubError.

        ``states`` maps each id GitHub returned to ``parse_state``'s dict; an id
        it could not resolve is left out. ``rate`` is ``{"cost", "remaining",
        "reset"}`` for GraphQL's budget: what this query cost, what is left
        (``x-ratelimit-remaining``) and when the window resets, as an aware
        datetime. GraphQL needs a token: without one this makes no request.
        """
        if not self.authenticated or not ids:
            return {}, None
        payload = json.dumps({"query": STATES_QUERY, "variables": {"ids": list(ids)}}).encode()
        status, body, headers = self._call(GRAPHQL, payload)
        if not self.authenticated:   # the token was refused; GraphQL has no anonymous reads
            return {}, None
        if status != 200:
            raise GitHubError("GraphQL answered HTTP %s" % status)
        try:
            data = json.loads(body.decode("utf-8"))["data"]
            nodes = data["nodes"]
            if not isinstance(nodes, list):
                raise TypeError
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            raise GitHubError("GraphQL returned an unexpected body") from None
        states = {}
        for node in nodes:
            if isinstance(node, dict) and node.get("id"):
                states[node["id"]] = parse_state(node)
        return states, _rate(data.get("rateLimit"), headers)


def _rate(body, headers):
    """GraphQL's budget after a query: the headers first, the body's ``rateLimit`` after."""
    body = body if isinstance(body, dict) else {}
    try:
        cost = max(int(body.get("cost") or 1), 1)
    except (TypeError, ValueError):
        cost = 1
    remaining = reset = None
    try:
        remaining = int(headers["x-ratelimit-remaining"])
        reset = datetime.fromtimestamp(int(headers["x-ratelimit-reset"]), timezone.utc)
    except (KeyError, TypeError, ValueError):
        try:
            remaining = int(body["remaining"])
            reset = _ts(body["resetAt"])
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    return {"cost": cost, "remaining": remaining, "reset": reset}
