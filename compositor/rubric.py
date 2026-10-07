"""Rubric v1 and the pure decision function.

Nothing in this module touches the filesystem or the clock: ``decide`` takes
the scanned pane set, the current time and the previous state, and returns the
pointer (the ``current.json`` body) plus the next state. The contracts it
implements are in ``docs/concept.md`` ("Rubric v1" and "Contracts v1").
"""

import re
from datetime import datetime, timedelta, timezone

SCHEMA = 1

PRIORITY = {
    "alert": 100,
    "attention": 80,
    "live": 70,
    "activity": 60,
    "focus": 50,
    "ambient": 40,
    "briefing": 0,
}

ORIGINS = ("operator", "fleet")
DEFAULT_ORIGIN = "fleet"
DEFAULT_DWELL_S = 20

PANE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
REQUIRED = ("class", "title", "created", "ttl_minutes", "author")


class Malformed(ValueError):
    """A manifest that parses badly or misses a required field."""


def iso(dt):
    """RFC 3339, UTC, whole seconds: the pointer's timestamp format."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    """Parse an RFC 3339 timestamp (``Z`` or an offset) into aware UTC."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)  # 3.9 has no "Z" support, hence above
    if dt.tzinfo is None:
        raise ValueError("no timezone")
    return dt.astimezone(timezone.utc)


def _positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value > 0)


def parse_manifest(pane_id, data):
    """Validate a decoded manifest and return the fields the rubric uses.

    Raises ``Malformed`` with a short reason on any contract violation.
    """
    if not isinstance(data, dict):
        raise Malformed("manifest is not a JSON object")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise Malformed("missing " + ", ".join(missing))
    cls = data["class"]
    if cls not in PRIORITY:
        raise Malformed("unknown class %r" % (cls,))
    if not isinstance(data["title"], str):
        raise Malformed("title is not a string")
    if not isinstance(data["author"], str):
        raise Malformed("author is not a string")
    try:
        created = parse_time(data["created"])
    except (ValueError, OverflowError):
        raise Malformed("created is not an RFC 3339 timestamp")
    if not _positive_number(data["ttl_minutes"]):
        raise Malformed("ttl_minutes is not a positive number")
    try:
        expires = created + timedelta(minutes=data["ttl_minutes"])
    except (OverflowError, ValueError):
        # A huge or infinite ttl must skip this pane, not kill the compositor.
        raise Malformed("ttl_minutes is out of range")
    origin = data.get("origin", DEFAULT_ORIGIN)
    if origin not in ORIGINS:
        raise Malformed("unknown origin %r" % (origin,))
    dwell = data.get("dwell_s", DEFAULT_DWELL_S)
    if not _positive_number(dwell):
        raise Malformed("dwell_s is not a positive number")
    return {
        "id": pane_id,
        "class": cls,
        "priority": PRIORITY[cls],
        "title": data["title"],
        "created": created,
        "expires": expires,
        "origin": origin,
        "dwell_s": dwell,
    }


def _candidate(entry, now):
    """Return ``(pane, skip_reason)`` for one scanned pane directory.

    ``pane`` is the parsed pane when it is live. ``skip_reason`` is set only
    for problems worth a log line (a bad id or a malformed manifest); a pane
    that is still being written or has expired is simply not live.
    """
    pane_id = entry["id"]
    if not PANE_ID.match(pane_id):
        return None, "invalid pane id"
    files = entry["files"]
    # Only the final names count: x.partial is a write in progress.
    if "pane.html" not in files or "manifest.json" not in files:
        return None, None
    data = entry.get("manifest")
    if isinstance(data, Malformed):
        return None, str(data)
    try:
        pane = parse_manifest(pane_id, data)
    except Malformed as exc:
        return None, str(exc)
    if pane["expires"] <= now:
        return None, None
    return pane, None


def _rank_key(pane):
    # priority desc, operator before fleet, created desc, id for determinism
    return (-pane["priority"], ORIGINS.index(pane["origin"]),
            -pane["created"].timestamp(), pane["id"])


def _rotate(group, now, prev):
    """Pick the showing pane of the top group; return ``(index, rotation)``.

    ``rotation`` is the next rotation state, or None for a single winner.
    """
    if len(group) == 1:
        return 0, None
    prev = prev or {}
    ids = [p["id"] for p in group]
    current = prev.get("pane")
    if current in ids:
        index = ids.index(current)
        elapsed = (now - datetime.fromisoformat(prev["since"])).total_seconds()
        if elapsed < group[index]["dwell_s"]:
            return index, dict(prev, index=index, group=ids)
        index = (index + 1) % len(ids)
    elif set(prev.get("group") or ()) & set(ids):
        # The showing pane left a group that carries on: its successor has
        # slid into its slot, so show that one rather than restarting.
        index = prev.get("index", 0) % len(ids)
    else:
        index = 0
    return index, {"pane": ids[index], "index": index,
                   "since": now.isoformat(), "group": ids}


def _pointer(now, url_base, **fields):
    pointer = {
        "schema": SCHEMA,
        "decided_at": iso(now),
        "pane": None,
        "url": None,
        "class": None,
        "priority": None,
        "title": None,
        "expires_at": None,
        "fallback": None,
        "rotation": None,
    }
    pointer.update(fields)
    return pointer


def _same(a, b):
    """Two pointers carry the same decision when all but ``decided_at`` match."""
    if a is None or b is None:
        return False
    strip = lambda p: {k: v for k, v in p.items() if k != "decided_at"}
    return strip(a) == strip(b)


def decide(panes, now, state, brief_present=True, url_base="http://pub.lan"):
    """Rank the bus and return ``(pointer, state)``.

    ``panes`` is a list of scanned pane directories, each a dict with ``id``
    (the directory name), ``files`` (the names in it) and ``manifest`` (the
    decoded ``manifest.json``, or a ``Malformed`` instance when it did not
    decode). ``now`` is an aware datetime. ``state`` is the previous state
    (``{}`` on first run); the returned state is JSON-serialisable.

    State keys: ``pointer`` (the last decision, so an unchanged decision keeps
    its ``decided_at``), ``rotation`` (the top group's rotation cursor) and
    ``skipped`` (pane id → reason, for log-once).
    """
    url_base = url_base.rstrip("/")
    live, skipped = [], {}
    for entry in panes:
        pane, reason = _candidate(entry, now)
        if pane is not None:
            live.append(pane)
        elif reason is not None:
            skipped[entry["id"]] = reason

    rotation_state = None
    if live:
        live.sort(key=_rank_key)
        top = live[0]
        group = [p for p in live if p["priority"] == top["priority"]
                 and p["origin"] == top["origin"]]
        index, rotation_state = _rotate(group, now, state.get("rotation"))
        win = group[index]
        pointer = _pointer(
            now, url_base,
            pane=win["id"],
            url="%s/viewport/panes/%s/pane.html" % (url_base, win["id"]),
            title=win["title"],
            expires_at=iso(win["expires"]),
            rotation=None if rotation_state is None else {
                "index": index, "of": len(group), "dwell_s": win["dwell_s"]},
            **{"class": win["class"], "priority": win["priority"]})
    elif brief_present:
        pointer = _pointer(
            now, url_base, url=url_base + "/brief/", title="Morning brief",
            fallback="briefing", **{"class": "briefing", "priority": 0})
    else:
        pointer = _pointer(
            now, url_base, url=url_base + "/viewport/status.html",
            title="No live pane on the bus and no briefing published",
            fallback="status")

    previous = state.get("pointer")
    if _same(pointer, previous):
        pointer = previous
    return pointer, {"pointer": pointer, "rotation": rotation_state,
                     "skipped": skipped}
