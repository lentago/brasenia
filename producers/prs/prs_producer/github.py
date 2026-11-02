"""The fleet's pull requests from GitHub's search API, unauthenticated.

Every ``lentago`` repository is public, so search without a token sees the
whole org, which suits a LAN-readable pane. Search has its own rate limit
(10 requests a minute without a token), apart from the 60-an-hour core
budget the focus producer paces itself against. One refresh is four
searches:

- the running list: the 50 most recently updated PRs. Each one's event time
  (merged, closed or opened) is never later than its ``updated_at``, so the
  newest events are among them unless more than 50 PRs were touched since
  without an event (comments, pushes);
- three counts, read from ``total_count`` with ``per_page=1``: open now,
  opened since local midnight, merged since local midnight.

Search results carry no check state, auto-merge or review decision; those
are core-API reads this producer does not make (brasenia#134).
"""

import json
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

# Logins that read better by role than by name; any other "[bot]" suffix is dropped.
ALIASES = {
    "lentago-claude-runner[bot]": "bullpen",
}


class GitHubError(Exception):
    """Any GitHub failure: network, rate limit, 5xx, or an unexpected body."""


def urllib_transport(url, headers, timeout=15):
    """GET ``url``; return ``(status, body)``. Raises OSError on network failure."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def search_url(query, per_page, sort=None):
    params = {"q": query, "per_page": per_page}
    if sort:
        params.update({"sort": sort, "order": "desc"})
    return ENDPOINT + urllib.parse.urlencode(params)


def _search(transport, query, per_page, sort=None):
    """``(total_count, items)`` for one search, or GitHubError."""
    try:
        status, body = transport(search_url(query, per_page, sort), HEADERS)
    except OSError as err:
        raise GitHubError("unreachable (%s)" % err) from None
    if status != 200:
        raise GitHubError("search answered HTTP %s" % status)
    try:
        doc = json.loads(body.decode("utf-8"))
        items = doc["items"]
        total = int(doc["total_count"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise GitHubError("search returned an unexpected body") from None
    return total, items if isinstance(items, list) else []


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def who(login):
    """A short name for the author: the runner App is "bullpen", "[bot]" is dropped."""
    if login in ALIASES:
        return ALIASES[login]
    return login[:-len("[bot]")] if login.endswith("[bot]") else login


def parse(item):
    """One search item as ``{"repo", "number", "title", "who", "status", "when"}``.

    ``status`` is ``merged``, ``closed`` (without merging), ``draft`` or
    ``open``; ``when`` is the time of that event: merged, closed or opened.
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
            "repo": item["repository_url"].rsplit("/repos/", 1)[1],
            "number": int(item["number"]),
            "title": str(item["title"]),
            "who": who(str(item["user"]["login"])),
            "status": status,
            "when": when,
        }
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def snapshot(since, scope=DEFAULT_SCOPE, transport=urllib_transport):
    """Counts and the running list, or GitHubError if any of the four searches fails.

    ``since`` is local midnight as an aware datetime; "today" counts start there.
    Returns ``{"open", "opened_today", "merged_today", "events"}``, with
    ``events`` newest first.
    """
    base = "%s is:pr" % scope
    day = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _, items = _search(transport, base, LIST_SIZE, sort="updated")
    open_now, _ = _search(transport, base + " is:open", 1)
    opened, _ = _search(transport, "%s created:>=%s" % (base, day), 1)
    merged, _ = _search(transport, "%s merged:>=%s" % (base, day), 1)
    events = [e for e in (parse(i) for i in items) if e is not None and e["when"] is not None]
    events.sort(key=lambda e: e["when"], reverse=True)
    return {"open": open_now, "opened_today": opened, "merged_today": merged, "events": events}
