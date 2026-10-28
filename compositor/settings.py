"""Household overrides for the rubric, read back from the configurator's log.

Defaults live in code: ``rubric.PRIORITY``, ``rubric.DEFAULT_DWELL_S``, and no
age limit on the briefing fallback. Overrides live on the share (ADR-0011).
``viewport/configure.html`` posts each change to pub-signals, which appends a
line to ``signals/rubric.jsonl``:

    {"ts": "...", "id": "priority.focus", "action": "set", "label": "60", "client": "..."}
    {"ts": "...", "id": "priority.focus", "action": "undo", "client": "..."}

``set`` carries the new value in ``label``; ``undo`` returns the setting to
its default. The latest valid action per setting wins. A value that does not
validate is rejected (it shows in the history and changes nothing), so a bad
line can never break the rubric.
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
    "With nothing live, show the morning brief only if it was published within "
    "this many hours; otherwise the status card. 0 turns the fallback off; "
    "empty means any age.")
SPEC["rotation.dwell_s"] = (
    5, 600, "Rotation: default seconds per pane",
    "How long each tied pane shows before the next, for panes whose manifest "
    "sets no dwell_s.")


def defaults():
    out = {"priority." + c: rubric.PRIORITY[c] for c in CLASSES}
    out["briefing.max_age_hours"] = None
    out["rotation.dwell_s"] = rubric.DEFAULT_DWELL_S
    return out


def parse_value(key, text):
    """The validated value of ``text`` for ``key``; ValueError with a reason."""
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
        if key not in SPEC:
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
        return False, "no brief/index.html is published"
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
