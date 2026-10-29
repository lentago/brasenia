"""The home pane: everything Home Assistant knows about the house, at a glance.

``summarize`` picks entities by domain and device class, so it works on any
Home Assistant without a list to maintain:

* **Alarm**: every ``alarm_control_panel``.
* **People**: every ``person``, except one whose state is ``unknown`` (a
  service account that never reports a location).
* **Climate**: every ``climate`` entity: the temperature, the set point, what
  it is doing and the humidity.
* **Doors & windows**: ``binary_sensor`` entities of class door, garage_door,
  window or opening, and ``cover`` entities of class garage, door, gate or
  window (not blinds or shades). Open ones come first.
* **Locks**: every ``lock``.
* **Water**: ``binary_sensor`` entities of class moisture (leak and rain
  sensors). A wet one is red.

``hide`` drops entity ids the household doesn't want on the wall.
``render_home`` lays them out in three columns: Alarm, People and Locks;
Climate (two-line rows) and Water; Doors & windows. Rows are fixed-height
slots and each column's height is shared out among its cards, so a long list
ends in "+N more" instead of pushing the others off the band.
"""

import html

from .style import AMBER, BLUE, allot, clock, degrees, page, whole

TITLE = "Home"
BAND, BAND_TEXT = "#1b3049", "#c9dbf0"
ROW_H, CLIMATE_ROW_H, CARD_CHROME, GAP, COLUMN_H = 38, 64, 52, 12, 550

OPENING_SENSORS = ("door", "garage_door", "window", "opening")
OPENING_COVERS = ("garage", "door", "gate", "window")
OFFLINE = ("unavailable", "unknown")

ALARM = {
    "disarmed": ("Disarmed", "muted"), "armed_home": ("Armed home", "ok"),
    "armed_away": ("Armed away", "ok"), "armed_night": ("Armed night", "ok"),
    "armed_vacation": ("Armed vacation", "ok"), "armed_custom_bypass": ("Armed custom", "ok"),
    "arming": ("Arming", "warn"), "pending": ("Pending", "warn"),
    "disarming": ("Disarming", "warn"), "triggered": ("Triggered", "bad"),
}
OPENING = {
    "on": ("Open", "warn"), "off": ("Closed", "muted"), "open": ("Open", "warn"),
    "closed": ("Closed", "muted"), "opening": ("Opening", "warn"), "closing": ("Closing", "warn"),
}
LOCK = {
    "locked": ("Locked", "muted"), "unlocked": ("Unlocked", ""), "open": ("Open", "warn"),
    "locking": ("Locking", "warn"), "unlocking": ("Unlocking", "warn"),
    "opening": ("Opening", "warn"), "jammed": ("Jammed", "bad"),
}
WATER = {"off": ("Dry", "muted"), "on": ("Wet", "bad")}
ACTION = {"heating": ("heating", "heat"), "cooling": ("cooling", "cool"), "idle": ("idle", "muted"),
          "off": ("off", "faint"), "drying": ("drying", "muted"), "fan": ("fan", "muted"),
          "preheating": ("preheating", "heat"), "defrosting": ("defrosting", "muted")}

CSS = """
.cols { display: flex; gap: 12px; margin-top: 12px; height: 550px; }
.col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.col.a { flex: 0 0 380px; }
.col.b { flex: 0 0 432px; }
.col.c { flex: 1 1 auto; }
.card { flex: 0 0 auto; }
.row { height: 38px; box-sizing: border-box; display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid #2a373e; }
.name { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.state { flex: 0 0 auto; white-space: nowrap; }
.climate { height: 64px; box-sizing: border-box; padding: 4px 0; border-bottom: 1px solid #2a373e;
  display: grid; grid-template-columns: 1fr auto; grid-template-rows: 28px 28px;
  align-items: center; column-gap: 12px; }
.climate .name { font-weight: bold; }
.climate .temp { grid-row: 1 / span 2; grid-column: 2; align-self: center; font-size: 34px;
  line-height: 40px; font-weight: bold; }
.climate .how { color: #9fb0b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.heat { color: %(heat)s; font-weight: bold; }
.cool { color: %(cool)s; font-weight: bold; }
.more { color: #9fb0b8; }
""" % {"heat": AMBER, "cool": BLUE}


def summarize(states, hide=()):
    """Home Assistant's state list → ``{group: [entry, ...]}`` for the pane.

    Entries are ``(name, label, tone)``, except climate, which is a dict.
    Unknown or unavailable entities read "Offline".
    """
    hide = set(hide)
    groups = {"alarm": [], "people": [], "climate": [], "openings": [], "locks": [], "water": []}
    for s in states:
        eid = s["entity_id"]
        if eid in hide:
            continue
        domain = eid.split(".", 1)[0]
        attrs = s.get("attributes") if isinstance(s.get("attributes"), dict) else {}
        state = s.get("state") if isinstance(s.get("state"), str) else "unknown"
        name = _name(attrs, eid)
        cls = attrs.get("device_class")
        if domain == "alarm_control_panel":
            groups["alarm"].append((name,) + _label(ALARM, state))
        elif domain == "person":
            if state == "unknown":
                continue
            groups["people"].append((name,) + _person(state))
        elif domain == "climate":
            groups["climate"].append(_climate(name, state, attrs))
        elif (domain == "binary_sensor" and cls in OPENING_SENSORS) or \
                (domain == "cover" and cls in OPENING_COVERS):
            groups["openings"].append((name,) + _label(OPENING, state))
        elif domain == "lock":
            groups["locks"].append((name,) + _label(LOCK, state))
        elif domain == "binary_sensor" and cls == "moisture":
            groups["water"].append((name,) + _label(WATER, state))
    for key in ("alarm", "people", "locks", "water"):
        groups[key].sort(key=lambda entry: entry[0].lower())
    # what needs a look first, then by name; offline last
    groups["openings"].sort(key=lambda entry: (_urgency(entry[2]), entry[0].lower()))
    groups["climate"].sort(key=lambda c: c["name"].lower())
    return groups


def render_home(groups, now, tz):
    """pane.html: the home at 1280×720."""
    columns = (("a", [("Alarm", groups["alarm"], ROW_H), ("People", groups["people"], ROW_H),
                      ("Locks", groups["locks"], ROW_H)]),
               ("b", [("Climate", groups["climate"], CLIMATE_ROW_H), ("Water", groups["water"], ROW_H)]),
               ("c", [("Doors & windows", groups["openings"], ROW_H)]))
    body = '<div class="cols">%s</div>' % "".join(
        '<div class="col %s">%s</div>' % (key, _column(cards)) for key, cards in columns)
    if not any(groups.values()):
        body = '<div class="cols"><div class="card none" style="flex:1">Home Assistant lists nothing ' \
               'for this pane yet.</div></div>'
    return page("Home", BAND, BAND_TEXT, CSS, "Home", _summary(groups), body,
                "Home Assistant · as of %s" % clock(now, tz))


def _column(cards):
    """The cards of one column, its 550 px shared out (small cards whole, then evenly)."""
    cards = [c for c in cards if c[1]]
    if not cards:
        return ""
    space = allot([CARD_CHROME + len(entries) * row_h for _, entries, row_h in cards],
                  COLUMN_H - (len(cards) - 1) * GAP)
    return "".join(_card(title, entries, max((px - CARD_CHROME) // row_h, 1))
                   for (title, entries, row_h), px in zip(cards, space))


def _card(title, entries, slots):
    e = html.escape
    shown, extra = _fit(entries, slots)
    cells = []
    for entry in shown:
        if isinstance(entry, dict):
            cells.append(_climate_row(entry))
        else:
            name, label, tone = entry
            cells.append('<div class="row"><span class="name">%s</span><span class="state %s">%s</span></div>'
                         % (e(name), tone, e(label)))
    if extra:
        cells.append('<div class="row more">+%d more</div>' % extra)
    return '<div class="card"><h2>%s</h2>%s</div>' % (e(title), "".join(cells))


def _fit(entries, slots):
    """``(shown, extra)``: all of them when they fit, else ``slots - 1`` and a "+N more"."""
    if len(entries) <= slots:
        return entries, 0
    keep = max(slots - 1, 0)
    return entries[:keep], len(entries) - keep


def _climate_row(c):
    e = html.escape
    label, tone = c["action"]
    how = " · ".join(x for x in (c["set"], '<span class="%s">%s</span>' % (tone, e(label)) if label else "",
                                 c["humidity"]) if x)
    return ('<div class="climate"><span class="name">%s</span><span class="temp">%s</span>'
            '<span class="how">%s</span></div>' % (e(c["name"]), e(c["current"]), how))


def _summary(groups):
    parts = []
    opened = sum(1 for _, _, tone in groups["openings"] if tone == "warn")
    wet = sum(1 for _, _, tone in groups["water"] if tone == "bad")
    triggered = any(tone == "bad" for _, _, tone in groups["alarm"])
    if triggered:
        parts.append('<span class="bad">Alarm triggered</span>')
    if wet:
        parts.append('<span class="bad">%d wet</span>' % wet)
    if groups["openings"]:
        parts.append("%d open" % opened if opened else "All closed")
    away = sum(1 for _, label, _ in groups["people"] if label != "Home")
    if groups["people"]:
        parts.append("everyone home" if not away else "%d of %d home" % (len(groups["people"]) - away,
                                                                       len(groups["people"])))
    return " · ".join(parts)


def _label(table, state):
    if state in OFFLINE:
        return ("Offline", "faint")
    return table.get(state, (state.replace("_", " ").capitalize(), ""))


def _person(state):
    if state == "home":
        return ("Home", "ok")
    if state == "not_home":
        return ("Away", "muted")
    if state == "unavailable":
        return ("Offline", "faint")
    return (state, "")   # the name of the zone they are in


def _climate(name, state, attrs):
    if state in OFFLINE:
        return {"name": name, "current": "–", "set": "", "action": ("Offline", "faint"), "humidity": ""}
    low, high = attrs.get("target_temp_low"), attrs.get("target_temp_high")
    if attrs.get("temperature") is not None:
        target = "set " + degrees(attrs.get("temperature"))
    elif low is not None and high is not None:
        target = "%s–%s" % (degrees(low), degrees(high))
    else:
        target = ""
    action = attrs.get("hvac_action")
    if state == "off":
        act = ("off", "faint")
        target = ""
    elif isinstance(action, str) and action:
        act = ACTION.get(action, (action, "muted"))
    else:
        act = (state.replace("_", " "), "muted")
    humidity = attrs.get("current_humidity")
    return {"name": name, "current": degrees(attrs.get("current_temperature")), "set": target,
            "action": act, "humidity": "%d%% RH" % whole(humidity)
            if isinstance(humidity, (int, float)) and not isinstance(humidity, bool) else ""}


def _urgency(tone):
    return {"bad": 0, "warn": 0, "": 1, "muted": 1, "ok": 1}.get(tone, 2)


def _name(attrs, entity_id):
    name = attrs.get("friendly_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return entity_id.split(".", 1)[1].replace("_", " ").capitalize()
