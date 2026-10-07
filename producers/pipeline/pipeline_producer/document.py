"""Fetch and validate pipeline.json (schema 1, pinned in lentago/drosera#266).

The document is served by drosera's producer on LXC 105 and proxied by pub's
Caddy at ``http://pub.lan/viewport/pipeline.json``; it needs no credential.
``file://`` URLs work too, which is how the fixtures are rendered by hand.
"""

import json
import urllib.request
from datetime import datetime, timezone

SCHEMA = 1
STAGES = ("pushed", "pr_open", "checks_green", "merged", "applied", "live")
HEADERS = {"Accept": "application/json", "User-Agent": "brasenia-pipeline-producer"}


class DocumentError(Exception):
    """pipeline.json is missing, unreadable, or not schema 1."""


def urllib_fetch(url, timeout=10):
    """GET ``url`` and return the body. Raises OSError (HTTPError included) on failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_ts(value):
    """RFC 3339 timestamp → aware UTC datetime (3.9's fromisoformat lacks 'Z')."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError("timestamp has no offset: %r" % value)
    return ts.astimezone(timezone.utc)


def load(fetch, url):
    """Return ``(generated_at, repos)`` from the document at ``url``.

    Only what the pane relies on is checked: ``schema`` 1, a parseable
    ``generated_at`` and a ``repos`` list of objects. Anything else raises
    DocumentError, which the producer treats as "nothing in flight".
    """
    try:
        doc = json.loads(fetch(url))
    except (OSError, ValueError) as err:
        raise DocumentError("unreadable: %s" % err) from err
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise DocumentError("not a schema-%d document" % SCHEMA)
    try:
        generated_at = parse_ts(doc["generated_at"])
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise DocumentError("bad generated_at: %s" % err) from err
    repos = doc.get("repos")
    if not isinstance(repos, list) or not all(isinstance(r, dict) for r in repos):
        raise DocumentError("repos is not a list of objects")
    return generated_at, repos


def in_flight(repos):
    """The repos with ``in_flight: true``, oldest ``in_flight_since`` first.

    A repo in flight with no (or a bad) ``in_flight_since`` sorts last.
    """
    late = datetime.max.replace(tzinfo=timezone.utc)

    def since(repo):
        try:
            return parse_ts(repo["in_flight_since"])
        except (KeyError, TypeError, ValueError, AttributeError):
            return late

    flying = [r for r in repos if r.get("in_flight") is True]
    return sorted(flying, key=lambda r: (since(r), str(r.get("repo", ""))))


def stages(repo):
    """The six stages in pipeline order, filling any the document left out with state 0."""
    by_name = {}
    for entry in repo.get("stages") or []:
        if isinstance(entry, dict) and entry.get("stage") in STAGES:
            by_name.setdefault(entry["stage"], entry)
    return [by_name.get(name, {"stage": name, "state": 0, "sha": None, "detail": None})
            for name in STAGES]
