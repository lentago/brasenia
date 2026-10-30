"""Household overrides for the rubric, read back from the configurator's log.

Defaults live in code: ``rubric.PRIORITY``, and no age limit on the briefing
fallback. Overrides live on the share (ADR-0011).
``viewport/configure.html`` posts each change to pub-signals, which appends a
line to ``signals/rubric.jsonl``:

    {"ts": "...", "id": "priority.focus", "action": "set", "label": "60", "client": "..."}
    {"ts": "...", "id": "priority.focus", "action": "undo", "client": "..."}

``set`` carries the new value in ``label``; ``undo`` returns the setting to
its default. The latest valid action per setting wins. A value that does not
validate is rejected (it shows in the history and changes nothing), so a bad
line can never break the rubric.

Besides the fixed settings in ``SPEC``, a ``link.<pane-id>`` setting is a
standing slot (#97, ADR-0018): a web page kept on the bus as a resting link
pane. Its value is a JSON object, ``{"title", "url"}`` plus any of the link
pane display fields, and ``undo`` removes the slot. The links producer reads
the validated slots back from ``viewport/rubric.json``.
"""

import json

from . import rubric

CLASSES = tuple(sorted((c for c in rubric.PRIORITY if c != "briefing"),
                       key=lambda c: -rubric.PRIORITY[c]))
HISTORY = 12

# key -> (minimum, maximum, label, help)
SPEC = {}
for _cls in CLASSES:
    SPEC["priority." + _cls] = (1, 999, "%s priority" % _cls,
                                "Rung for %s panes. Higher wins." % _cls)
SPEC["briefing.max_age_hours"] = (
    0, 8760, "Briefing fallback: maximum age (hours)",
    "With nothing live, show the briefing (the Family Brief) only if it was "
    "published within this many hours; otherwise the status card. 0 turns the "
    "fallback off; empty means any age.")
# rotation.dwell_s retired with rotation (ADR-0020): an old line in the log
# is listed as an unknown setting and changes nothing.
# Not a number: a pane id (lo/hi unused). Set from the Roku remote's
# Left/Right as well as from configure.html (#83).
SPEC["default.pane"] = (
    None, None, "Default resting pane",
    "The resting (ambient) pane shown when nothing more urgent is up. Unset, "
    "the first resting pane by id shows. Left/Right on the Roku remote sets it too.")


LINK_PREFIX = "link."
MAX_TITLE = 120


def is_link(key):
    """A standing-slot setting: ``link.`` and a valid pane id."""
    return (isinstance(key, str) and key.startswith(LINK_PREFIX)
            and bool(rubric.PANE_ID.match(key[len(LINK_PREFIX):])))


def parse_link(text):
    """A standing slot's value: ``{"title", "source"}`` from its JSON label."""
    try:
        data = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
        raise ValueError("title must be 1-%d characters" % MAX_TITLE)
    try:
        source = rubric.parse_source({k: v for k, v in data.items() if k != "title"})
    except rubric.Malformed as exc:
        raise ValueError(str(exc))
    return {"title": title.strip(), "source": source}


def links(eff):
    """The standing slots in effect, pane id -> ``{"title", "source"}``."""
    return {k[len(LINK_PREFIX):]: v for k, v in sorted(eff.items()) if is_link(k)}


def defaults():
    out = {"priority." + c: rubric.PRIORITY[c] for c in CLASSES}
    out["briefing.max_age_hours"] = None
    out["default.pane"] = None
    return out


def parse_value(key, text):
    """The validated value of ``text`` for ``key``; ValueError with a reason."""
    if is_link(key):
        return parse_link(text)
    if key == "default.pane":
        if not isinstance(text, str) or not rubric.PANE_ID.match(text.strip()):
            raise ValueError("not a pane id: %r" % (text,))
        return text.strip()
    lo, hi = SPEC[key][:2]
    if not isinstance(text, str) or not text.strip().lstrip("-").isdigit():
        raise ValueError("not a whole number: %r" % (text,))
    value = int(text.strip())
    if not lo <= value <= hi:
        raise ValueError("%d is outside %d-%d" % (value, lo, hi))
    return value


def load(path):
    """Read the log at ``path``; return ``(overrides, history)``.

    ``overrides`` maps setting → value. ``history`` is the last ``HISTORY``
    entries, newest first, each ``{ts, key, action, value, client, error}``
    (``error`` set when the entry was rejected). A missing log means no
    overrides; unparseable lines are skipped.
    """
    overrides, history = {}, []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return overrides, history
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        key, action = rec.get("id"), rec.get("action")
        entry = {"ts": rec.get("ts"), "key": key, "action": action, "value": None,
                 "client": rec.get("client"), "error": None}
        if key not in SPEC and not is_link(key):
            entry["error"] = "unknown setting"
        elif action == "undo":
            overrides.pop(key, None)
        elif action == "set":
            try:
                entry["value"] = overrides[key] = parse_value(key, rec.get("label"))
            except ValueError as exc:
                entry["error"] = str(exc)
        else:
            entry["error"] = "unknown action"
        history.append(entry)
    return overrides, history[::-1][:HISTORY]


def effective(overrides):
    out = defaults()
    out.update(overrides)
    return out


def priorities(eff):
    """The class → priority map ``rubric.decide`` takes."""
    out = {c: eff["priority." + c] for c in CLASSES}
    out["briefing"] = rubric.PRIORITY["briefing"]
    return out


def brief_usable(brief, eff, now):
    """Whether the briefing fallback may use this brief; ``(ok, why_not)``."""
    if not brief["present"]:
        return False, "no briefing is published"
    limit = eff["briefing.max_age_hours"]
    if limit is None:
        return True, None
    if limit == 0:
        return False, "the briefing fallback is turned off"
    if brief["mtime"] is None or (now - brief["mtime"]).total_seconds() > limit * 3600:
        return False, "older than the %d h limit" % limit
    return True, None


def document(eff, overrides, history):
    """The body of ``viewport/rubric.json``: effective settings and where they came from."""
    return {
        "schema": 1,
        "effective": eff,
        "overrides": overrides,
        "defaults": defaults(),
        "source": "signals/rubric.jsonl (written by viewport/configure.html via pub-signals)",
        "last_change": next((h for h in history if not h["error"]), None),
    }
