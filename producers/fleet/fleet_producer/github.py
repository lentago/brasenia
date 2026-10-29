"""Open agent PRs from GitHub's search API, unauthenticated.

The bullpen opens its pull requests as the ``lentago-claude-runner`` GitHub
App, so one search finds every open one: the same query as the Claytonia
dashboard's "Open agent PRs" panel, without the ``org:`` filter so a project
outside the org (``cpitzi/music-curator``) is included. Unauthenticated
search sees public repositories only, which suits a LAN-readable pane.

Search has its own rate limit (10 requests a minute without a token), apart
from the 60-an-hour core budget the focus producer paces itself against, and
the producer asks once every few minutes.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

QUERY = "is:pr is:open author:app/lentago-claude-runner"
URL = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
    {"q": QUERY, "sort": "created", "order": "asc", "per_page": 50})
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "brasenia-fleet-producer",
    "X-GitHub-Api-Version": "2022-11-28",
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


def agent_prs(transport=urllib_transport):
    """``(total, [{"repo", "number", "title", "created", "draft"}])``, oldest first."""
    try:
        status, body = transport(URL, HEADERS)
    except OSError as err:
        raise GitHubError("unreachable (%s)" % err) from None
    if status != 200:
        raise GitHubError("search answered HTTP %s" % status)
    try:
        doc = json.loads(body.decode("utf-8"))
        items = doc["items"]
        total = int(doc.get("total_count", len(items)))
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise GitHubError("search returned an unexpected body") from None
    prs = []
    for item in items if isinstance(items, list) else ():
        try:
            prs.append({
                "repo": item["repository_url"].rsplit("/repos/", 1)[1],
                "number": int(item["number"]),
                "title": str(item["title"]),
                "created": datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
                "draft": item.get("draft") is True,
            })
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            continue
    return total, prs
