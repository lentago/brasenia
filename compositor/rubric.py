"""Rubric v1 and the pure decision function.

Nothing in this module touches the filesystem or the clock: ``decide`` takes
the scanned pane set, the current time and the previous state, and returns the
pointer (the ``current.json`` body) plus the next state. The contracts it
implements are in ``docs/concept.md`` ("Rubric v1" and "Contracts v1").
"""

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

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
# The briefing slot the fallback shows (written by the family-brief producer).
BRIEFING_PATH = "/viewport/briefing/pane.html"
BRIEFING_TITLE = "Briefing"
DEFAULT_ORIGIN = "fleet"
DEFAULT_DWELL_S = 20

PANE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
REQUIRED = ("class", "title", "created", "ttl_minutes", "author")

# A link pane (#96, ADR-0016) names a web page in its manifest's `source`
# instead of shipping pane.html. These are the source fields and their defaults.
SOURCE_DEFAULTS = {"theme": "dark", "screens": 1, "viewport": [1280, 720],
                   "refresh_s": 60}
THEMES = ("dark", "light")
VIEWPORT_RANGE = (240, 3840)   # CSS pixels, each of width and height
MIN_REFRESH_S = 10
LINK_PANES_OFF = ("link panes are off until the renderer can show web pages "
                  "safely (lentago/kalmia#194)")


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


def _finite_positive(value):
    """A positive number that survives JSON: 1e309 parses as infinity, which
    would reach current.json as the non-JSON token Infinity."""
    return _positive_number(value) and math.isfinite(value)


def _whole(value, low, high):
    return (isinstance(value, int) and not isinstance(value, bool)
            and low <= value <= high)


def parse_source(source):
    """Validate a link pane's ``source`` and return it with defaults filled in.

    Keys beyond the contract's are dropped, so a newer writer's extra field
    does not make an older compositor skip the pane. Raises ``Malformed``.
    """
    if not isinstance(source, dict):
        raise Malformed("source is not a JSON object")
    url = source.get("url")
    if (not isinstance(url, str) or len(url) > 2048
            or any(c.isspace() for c in url)):
        raise Malformed("source.url is not a URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise Malformed("source.url is not a URL")
    if parts.scheme not in ("http", "https") or not host:
        raise Malformed("source.url is not an http(s) URL")
    if parts.username is not None or parts.password is not None:
        # The pointer and the line-up are readable by anyone on the LAN.
        raise Malformed("source.url carries credentials")
    out = dict(SOURCE_DEFAULTS, url=url)
    for key in SOURCE_DEFAULTS:
        if key in source:
            out[key] = source[key]
    if out["theme"] not in THEMES:
        raise Malformed("source.theme is not one of %s" % ", ".join(THEMES))
    if not _whole(out["screens"], 1, 4):
        raise Malformed("source.screens is not 1-4")
    viewport = out["viewport"]
    if not (isinstance(viewport, list) and len(viewport) == 2
            and all(_whole(v, *VIEWPORT_RANGE) for v in viewport)):
        raise Malformed("source.viewport is not [width, height] in CSS pixels "
                        "(%d-%d)" % VIEWPORT_RANGE)
    out["viewport"] = list(viewport)
    if not _finite_positive(out["refresh_s"]) or out["refresh_s"] < MIN_REFRESH_S:
        raise Malformed("source.refresh_s is not a number of seconds >= %d"
                        % MIN_REFRESH_S)
    return out


def source_rev(source):
    """A link pane's revision: a hash of its validated source, so changing the
    page or how it is shown counts as new content."""
    text = json.dumps(source, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _is_link(data):
    return isinstance(data, dict) and "source" in data


def _being_written(entry):
    """A pane directory without its final files is a write in progress (only
    the final names count: x.partial is still being written). A link pane
    needs only its manifest; any other pane also needs pane.html."""
    files = entry["files"]
    if "manifest.json" not in files:
        return True
    return "pane.html" not in files and not _is_link(entry.get("manifest"))


def parse_manifest(pane_id, data, priority=None, default_dwell=None):
    """Validate a decoded manifest and return the fields the rubric uses.

    ``priority`` maps class → priority (default ``PRIORITY``) and
    ``default_dwell`` is the dwell for a manifest without ``dwell_s``
    (default ``DEFAULT_DWELL_S``); the compositor passes the household's
    overrides (ADR-0011). Raises ``Malformed`` with a short reason on any
    contract violation.
    """
    priority = PRIORITY if priority is None else priority
    default_dwell = DEFAULT_DWELL_S if default_dwell is None else default_dwell
    if not isinstance(data, dict):
        raise Malformed("manifest is not a JSON object")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise Malformed("missing " + ", ".join(missing))
    cls = data["class"]
    if cls not in priority:
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
    dwell = data.get("dwell_s", default_dwell)
    if not _finite_positive(dwell):
        raise Malformed("dwell_s is not a positive number")
    source = parse_source(data["source"]) if "source" in data else None
    return {
        "id": pane_id,
        "class": cls,
        "priority": priority[cls],
        "title": data["title"],
        "created": created,
        "expires": expires,
        "origin": origin,
        "dwell_s": dwell,
        "source": source,
    }


def _parse_entry(entry, priority, default_dwell):
    """Parse a scanned pane directory whose files are in place, adding its
    revision: ``rev`` from the scan (a hash of pane.html), or for a link pane
    the hash of its source. Raises ``Malformed``."""
    data = entry.get("manifest")
    if isinstance(data, Malformed):
        raise data
    pane = parse_manifest(entry["id"], data, priority, default_dwell)
    pane["rev"] = (source_rev(pane["source"]) if pane["source"] is not None
                   else entry.get("rev"))
    return pane


def _candidate(entry, now, priority=None, default_dwell=None, link_panes=False):
    """Return ``(pane, skip_reason)`` for one scanned pane directory.

    ``pane`` is the parsed pane when it is live. ``skip_reason`` is set only
    for problems worth a log line (a bad id, a malformed manifest, or a link
    pane while link panes are off); a pane that is still being written or has
    expired is simply not live.
    """
    if not PANE_ID.match(entry["id"]):
        return None, "invalid pane id"
    if _being_written(entry):
        return None, None
    try:
        pane = _parse_entry(entry, priority, default_dwell)
    except Malformed as exc:
        return None, str(exc)
    if pane["expires"] <= now:
        return None, None
    if pane["source"] is not None and not link_panes:
        return None, LINK_PANES_OFF
    return pane, None


def _is_default(pane, default_pane):
    """The household's default resting pane (#83): only an ambient pane qualifies."""
    return default_pane is not None and pane["id"] == default_pane and pane["class"] == "ambient"


def _rank_key(default_pane=None):
    # priority desc, the household's default resting pane first within its
    # rung, operator before fleet, created desc, id for determinism. Resting
    # (ambient) panes skip the created step and keep a fixed order by id
    # (#86): each producer rewrites created on its own cadence, which would
    # reshuffle their rotation and the remote's Left/Right order.
    return lambda pane: (-pane["priority"], 0 if _is_default(pane, default_pane) else 1,
                         ORIGINS.index(pane["origin"]),
                         0 if pane["class"] == "ambient" else -pane["created"].timestamp(),
                         pane["id"])


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
        "rev": None,
        "source": None,
    }
    pointer.update(fields)
    return pointer


def _same(a, b):
    """Two pointers carry the same decision when all but ``decided_at`` and
    ``expires_at`` match: a producer renewing its pane moves the expiry
    without changing what is shown (#96)."""
    if a is None or b is None:
        return False
    strip = lambda p: {k: v for k, v in p.items()
                       if k not in ("decided_at", "expires_at")}
    return strip(a) == strip(b)


def decide(panes, now, state, brief_present=True, url_base="http://pub.lan",
           priority=None, default_dwell=None, briefing_title=BRIEFING_TITLE,
           default_pane=None, link_panes=False, brief_rev=None):
    """Rank the bus and return ``(pointer, state)``.

    ``panes`` is a list of scanned pane directories, each a dict with ``id``
    (the directory name), ``files`` (the names in it) and ``manifest`` (the
    decoded ``manifest.json``, or a ``Malformed`` instance when it did not
    decode). ``now`` is an aware datetime. ``state`` is the previous state
    (``{}`` on first run); the returned state is JSON-serialisable.

    ``priority`` and ``default_dwell`` override ``PRIORITY`` and
    ``DEFAULT_DWELL_S`` (see ``parse_manifest``). With nothing live and
    ``brief_present``, the pointer names the briefing slot (``BRIEFING_PATH``),
    titled ``briefing_title``. ``default_pane`` is the household's default
    resting pane: when it is live and ``ambient`` it ranks first in its rung
    and holds rather than taking turns. Link panes (a manifest ``source``)
    are skipped unless ``link_panes``. ``brief_rev`` is the briefing page's
    revision, carried in the pointer when the briefing is shown.

    The pointer's ``rev`` is the shown pane's revision, so a change of content
    is a new decision; a renewal that only moves ``expires_at`` is not (#96).

    State keys: ``pointer`` (the last decision, so an unchanged decision keeps
    its ``decided_at``), ``rotation`` (the top group's rotation cursor) and
    ``skipped`` (pane id → reason, for log-once).
    """
    url_base = url_base.rstrip("/")
    live, skipped = [], {}
    for entry in panes:
        pane, reason = _candidate(entry, now, priority, default_dwell, link_panes)
        if pane is not None:
            live.append(pane)
        elif reason is not None:
            skipped[entry["id"]] = reason

    rotation_state = None
    if live:
        live.sort(key=_rank_key(default_pane))
        top = live[0]
        if _is_default(top, default_pane):
            group = [top]   # the default holds; the other resting panes wait
        else:
            group = [p for p in live if p["priority"] == top["priority"]
                     and p["origin"] == top["origin"]]
        index, rotation_state = _rotate(group, now, state.get("rotation"))
        win = group[index]
        source = win["source"]
        pointer = _pointer(
            now, url_base,
            pane=win["id"],
            url=pane_url(win, url_base),
            title=win["title"],
            expires_at=iso(win["expires"]),
            rotation=None if rotation_state is None else {
                "index": index, "of": len(group), "dwell_s": win["dwell_s"]},
            rev=win["rev"],
            source=None if source is None else dict(source),
            **{"class": win["class"], "priority": win["priority"]})
    elif brief_present:
        pointer = _pointer(
            now, url_base, url=url_base + BRIEFING_PATH, title=briefing_title,
            fallback="briefing", rev=brief_rev, **{"class": "briefing", "priority": 0})
    else:
        pointer = _pointer(
            now, url_base, url=url_base + "/viewport/status.html",
            title="No live pane on the bus and no briefing published",
            fallback="status")

    previous = state.get("pointer")
    if _same(pointer, previous):
        # Same decision: keep its decided_at, and its object when nothing at
        # all changed, but carry a renewed expires_at.
        pointer = (previous if pointer["expires_at"] == previous.get("expires_at")
                   else dict(pointer, decided_at=previous["decided_at"]))
    return pointer, {"pointer": pointer, "rotation": rotation_state,
                     "skipped": skipped}


def pane_url(pane, url_base):
    """What a client shows for a pane: its source page for a link pane,
    otherwise its pane.html on the bus."""
    if pane.get("source") is not None:
        return pane["source"]["url"]
    return "%s/viewport/panes/%s/pane.html" % (url_base.rstrip("/"), pane["id"])


# explain() statuses, in the order the board lists them.
STATUSES = ("showing", "rotating", "outranked", "off", "expired", "writing",
            "malformed", "invalid")


def explain(panes, now, pointer, priority=None, default_dwell=None, default_pane=None,
            link_panes=False):
    """Say what happened to every scanned pane directory under ``pointer``.

    Returns one dict per entry, live panes first in rank order: the parsed
    fields (``class``, ``priority``, ``title``, ``origin``, ``created``,
    ``expires``, ``dwell_s``, ``source``, ``rev``; absent when the manifest
    did not parse), plus ``id``, ``status`` (one of ``STATUSES``) and
    ``reason`` (a short phrase, or None). ``pointer`` is the decision
    ``decide`` returned for the same ``panes``, ``now``, ``priority``,
    ``default_dwell`` and ``link_panes``; this function only explains it.
    """
    live, rest = [], []
    for entry in panes:
        pane_id = entry["id"]
        if not PANE_ID.match(pane_id):
            rest.append({"id": pane_id, "status": "invalid", "reason": "invalid pane id"})
            continue
        if _being_written(entry):
            files = entry["files"]
            missing = [n for n in ("pane.html", "manifest.json") if n not in files]
            rest.append({"id": pane_id, "status": "writing",
                         "reason": "no " + " or ".join(missing) + " yet"})
            continue
        try:
            pane = _parse_entry(entry, priority, default_dwell)
        except Malformed as exc:
            rest.append({"id": pane_id, "status": "malformed", "reason": str(exc)})
            continue
        if pane["expires"] <= now:
            rest.append(dict(pane, status="expired",
                             reason="expired at " + iso(pane["expires"])))
            continue
        if pane["source"] is not None and not link_panes:
            rest.append(dict(pane, status="off", reason=LINK_PANES_OFF))
            continue
        live.append(pane)

    live.sort(key=_rank_key(default_pane))
    shown = pointer.get("pane")
    win = next((p for p in live if p["id"] == shown), None)
    rows = []
    for p in live:
        if p is win:
            status, reason = "showing", None
        elif win is not None and _is_default(win, default_pane) and p["priority"] == win["priority"]:
            status, reason = "outranked", "%s is the household's default resting pane" % win["id"]
        elif win is not None and (p["priority"], p["origin"]) == (win["priority"], win["origin"]):
            status, reason = "rotating", "takes turns with %s every %ss" % (win["id"], p["dwell_s"])
        else:
            status, reason = "outranked", None
            if win is None:
                pass
            elif p["priority"] < win["priority"]:
                reason = "lower priority than %s (%s %d)" % (win["id"], win["class"], win["priority"])
            else:
                reason = "same priority as %s; %s panes go first" % (win["id"], win["origin"])
        rows.append(dict(p, status=status, reason=reason))
    order = {s: i for i, s in enumerate(STATUSES)}
    rest.sort(key=lambda r: (order[r["status"]], r["id"]))
    return rows + rest
