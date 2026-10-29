"""The slot file: which dashboards become panes, and how each is rendered.

A JSON object with a ``slots`` list; each slot is one pane::

    {"slots": [{"pane": "grafana-infra", "uid": "firewalla-infra-health",
                "title": "Infrastructure", "size": [1232, 610], "theme": "dark",
                "refresh_s": 300}]}

``pane``, ``uid`` and ``title`` are required; everything else has the default
in DEFAULTS. ``size`` is the CSS size Grafana lays the dashboard out at; the
pane scales it to fit its frame (FRAME in render.py), so the default renders
it 1:1. Grafana Cloud refuses a width under 1000 or a height under 500, and
its renderer one over 3000 (ADR-0017), so ``size`` plus ``crop_px`` must fit.
``crop_px`` is the strip rendered below ``size`` and cut off, which holds
Grafana's "Powered by" footer.
"""

import json
import math
import re

PANE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")    # Contracts v1
UID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")             # Grafana's dashboard UID
VAR_NAME = re.compile(r"[A-Za-z0-9_]{1,64}\Z")

MIN_REFRESH_S = 60
MIN_W, MIN_H, MAX_PX = 1000, 500, 3000

DEFAULTS = {
    "size": [1232, 610],
    "theme": "dark",
    "refresh_s": 300,
    "from": "now-6h",
    "to": "now",
    "vars": {},
    "crop_px": 40,
    "scale": 1,
    "dwell_s": 60,
    "org_id": 1,
}
KEYS = {"pane", "uid", "title"} | set(DEFAULTS)


class SlotError(Exception):
    """The slot file is unreadable or a slot breaks a rule; the message names it."""


class Slot:
    def __init__(self, pane, uid, title, size, theme, refresh_s, time_from, time_to, vars,
                 crop_px, scale, dwell_s, org_id):
        self.pane, self.uid, self.title = pane, uid, title
        self.size, self.theme, self.refresh_s = tuple(size), theme, refresh_s
        self.time_from, self.time_to, self.vars = time_from, time_to, dict(vars)
        self.crop_px, self.scale, self.dwell_s, self.org_id = crop_px, scale, dwell_s, org_id

    def __repr__(self):
        return "Slot(%s: %s)" % (self.pane, self.uid)


def _number(value, low, high, what, integer=True):
    ok = (not isinstance(value, bool) and isinstance(value, (int, float))
          and math.isfinite(value) and low <= value <= high
          and (not integer or value == int(value)))
    if not ok:
        raise SlotError("%s must be %s from %s to %s" % (
            what, "a whole number" if integer else "a number", low, high))
    return int(value) if integer else value


def _text(value, what, pattern=None):
    if not isinstance(value, str) or not value.strip() or (pattern and not pattern.match(value)):
        raise SlotError("%s %r is not valid" % (what, value))
    return value


def parse_slot(raw, where):
    if not isinstance(raw, dict):
        raise SlotError("%s is not an object" % where)
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise SlotError("%s has unknown keys: %s" % (where, ", ".join(unknown)))
    for key in ("pane", "uid", "title"):
        if key not in raw:
            raise SlotError("%s has no %r" % (where, key))
    s = dict(DEFAULTS, **raw)
    pane = _text(s["pane"], where + " pane", PANE_ID)
    where = "slot %r" % pane
    uid = _text(s["uid"], where + " uid", UID)
    title = _text(s["title"], where + " title")
    size = s["size"]
    if not (isinstance(size, list) and len(size) == 2):
        raise SlotError("%s size must be [width, height]" % where)
    crop = _number(s["crop_px"], 0, 200, where + " crop_px")
    width = _number(size[0], MIN_W, MAX_PX, where + " width")
    height = _number(size[1], MIN_H - crop, MAX_PX - crop,
                     where + " height (with crop_px %d)" % crop)
    theme = s["theme"]
    if theme not in ("dark", "light"):
        raise SlotError("%s theme must be dark or light" % where)
    refresh = _number(s["refresh_s"], MIN_REFRESH_S, 86400, where + " refresh_s")
    time_from = _text(s["from"], where + " from")
    time_to = _text(s["to"], where + " to")
    variables = s["vars"]
    if not isinstance(variables, dict) or not all(
            isinstance(k, str) and VAR_NAME.match(k) and isinstance(v, str)
            for k, v in variables.items()):
        raise SlotError("%s vars must map variable names to strings" % where)
    scale = _number(s["scale"], 1, 3, where + " scale")
    dwell = _number(s["dwell_s"], 1, 3600, where + " dwell_s")
    org_id = _number(s["org_id"], 1, 2 ** 31, where + " org_id")
    return Slot(pane, uid, title, (width, height), theme, refresh, time_from, time_to,
                variables, crop, scale, dwell, org_id)


def parse(doc):
    """The slots in ``doc`` (the file's parsed JSON), in file order."""
    if not isinstance(doc, dict) or not isinstance(doc.get("slots"), list):
        raise SlotError('the slot file must be an object with a "slots" list')
    slots, seen = [], set()
    for i, raw in enumerate(doc["slots"]):
        slot = parse_slot(raw, "slot %d" % (i + 1))
        if slot.pane in seen:
            raise SlotError("two slots write pane %r" % slot.pane)
        seen.add(slot.pane)
        slots.append(slot)
    return slots


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as err:
        raise SlotError("cannot read the slot file %s: %s" % (path, err)) from None
    return parse(doc)
