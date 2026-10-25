"""Fetch the Family Brief document and pick out today and tomorrow.

The document is the same JSON the Family Brief routine stores on its
dashboard page (schema 1). The routine also drops it in the Drive folder pub
publishes, so it reaches this producer at
``http://pub.lan/family-brief/latest.json`` with no credential. ``file://``
URLs work too, which is how the fixtures are rendered by hand.
"""

import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone

SCHEMA = 1
HEADERS = {"Accept": "application/json", "User-Agent": "brasenia-family-brief-producer"}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class DocumentError(Exception):
    """The document is missing, unreadable, or not schema 1."""


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


def parse_day(value):
    """``YYYY-MM-DD`` → date; ValueError for anything else."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("not a YYYY-MM-DD date: %r" % (value,))
    return date.fromisoformat(value)


def load(fetch, url):
    """Return the parsed document at ``url``.

    Only what the pane relies on is checked: ``schema`` 1 and a ``date``.
    Every section is optional to the renderer, which shows what is there.
    """
    try:
        doc = json.loads(fetch(url))
    except (OSError, ValueError) as err:
        raise DocumentError("unreadable: %s" % err) from err
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise DocumentError("not a schema-%d document" % SCHEMA)
    try:
        parse_day(doc.get("date"))
    except ValueError as err:
        raise DocumentError("bad date: %s" % err) from err
    return doc


def is_fresh(doc, today):
    """A brief is fresh on its own day and the day after (until the next run lands)."""
    brief_day = parse_day(doc["date"])
    return brief_day in (today, today - timedelta(days=1))


def _list(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def week_day(doc, day):
    """The ``this_week`` entry for ``day`` (its items), or None when the brief has none."""
    for entry in _list(doc.get("this_week")):
        if entry.get("date") == day.isoformat():
            return _list(entry.get("items"))
    return None


def days(doc, today):
    """``(today_items, coverage, tomorrow_items)`` for the wall.

    On the brief's own day, today comes from ``today`` (with its coverage
    callout). On the day after, it comes from that day's ``this_week`` entry
    and there is no coverage line. Tomorrow always comes from ``this_week``;
    a day the brief lists nothing for is an empty list.
    """
    brief_day = parse_day(doc["date"])
    if brief_day == today:
        block = doc.get("today") if isinstance(doc.get("today"), dict) else {}
        today_items = _list(block.get("items"))
        coverage = block.get("coverage") if isinstance(block.get("coverage"), str) else None
    else:
        today_items = week_day(doc, today) or []
        coverage = None
    tomorrow_items = week_day(doc, today + timedelta(days=1)) or []
    return today_items, coverage, tomorrow_items


def touching(entries, wanted, field):
    """Entries whose ``field`` (a date or a list of dates) names one of ``wanted``."""
    keys = {d.isoformat() for d in wanted}
    out = []
    for entry in _list(entries):
        value = entry.get(field)
        values = value if isinstance(value, list) else [value]
        if any(isinstance(v, str) and v in keys for v in values):
            out.append(entry)
    return out
