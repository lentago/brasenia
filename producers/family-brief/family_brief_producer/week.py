"""Render the family week: panes/family-week/pane.html.

The Family Brief's seven days from today, one row per day: the day, any
coverage flag the brief raised for it (a gap, a crunch), how many decisions
and to-dos land on it, and its items. ``render_week`` is one 1920×1080 band
(the pane contract's canvas, ADR-0019). Like the today pane (ADR-0023), nothing
is cut with an ellipsis: a day's items wrap, the page picks the largest body
size (down to the 20 px floor) at which all seven days fit, and the rows
stretch to fill the band. Only a week too full for the floor drops items from
its busiest days into "+N more". It is a resting pane (``ambient``) the household can make the default
from the Roku remote (#83).
"""

import html
from datetime import timedelta

from .document import parse_day, touching, week_day
from .render import (AMBER, BAND, BAND_TEXT, BG, CARD, FAINT, FLOOR, LINE, MUTED, NEUTRAL, TEXT,
                     _colours, _edition, _edition_size, _lines, _people, _text, _width)

DAYS = 7
FLAGS = {"gap": "coverage gap", "crunch": "crunch day"}

BASE_CSS = """
html, body { margin: 0; padding: 0; }
body { overflow: hidden; position: relative; background: %(bg)s; color: %(text)s;
  font-family: "DejaVu Sans", sans-serif; }
header { display: flex; align-items: center; gap: 30px; background: %(band)s;
  box-sizing: border-box; }
h1 { margin: 0; color: #ffffff; white-space: nowrap; }
h1 span { color: %(band_text)s; font-weight: normal; }
.edition { margin-left: auto; color: %(band_text)s; max-width: 960px; text-align: right;
  overflow-wrap: anywhere; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.day { box-sizing: border-box; display: flex; border-left: 9px solid %(line)s;
  border-bottom: 1.5px solid %(line)s; background: %(card)s; overflow: hidden; }
.day.flagged { border-left-color: %(amber)s; }
.day.today { background: #1d2a30; }
.dlabel { flex: 0 0 auto; }
.dlabel b { display: block; }
.dlabel .md { color: %(muted)s; }
.chip { display: inline-block; margin-right: 15px; color: %(amber)s; font-weight: bold; white-space: nowrap; }
.chip.quiet { color: %(muted)s; font-weight: normal; }
.who { font-weight: bold; color: var(--pc); }
.time { color: %(muted)s; }
.none { color: %(faint)s; font-style: italic; }
.foot { position: absolute; color: %(faint)s; white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "text": TEXT, "band": BAND, "band_text": BAND_TEXT, "amber": AMBER,
       "line": LINE, "card": CARD, "muted": MUTED, "faint": FAINT}

# The wall cut, 1920×1080 CSS: a 90 px header, an 18 px gap and the seven day
# rows fill the 933 px main area, which ends at y=969 above the clock corner.
# The rows share the 825 px left over, each growing from its own height.
BIGGEST = 44
WEEK_H = 933 - 90 - 18
DAY_PAD, DAY_GAP, DAY_BAR = 9, 21, 9
DAY_W = 1920 - 2 * 36 - DAY_BAR - 2 * 18

PANE_CSS = BASE_CSS + """
body { width: 1920px; height: 1080px; font-size: %(body)spx; line-height: %(lh)spx; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px; overflow: hidden; }
header { height: 90px; border-radius: 15px; padding: 0 27px; margin-bottom: 18px; }
h1 { font-size: 48px; line-height: 60px; }
h1 span { font-size: 33px; }
.edition { font-size: %(ed)spx; line-height: %(ed_lh)spx; }
.week { display: flex; flex-direction: column; height: %(week_h)spx; }
.day { flex: 1 0 auto; padding: 9px 18px; gap: 21px; }
.dlabel { width: %(label_w)spx; font-size: %(label)spx; line-height: %(lh)spx; white-space: nowrap; }
.dlabel b { display: inline; }
.dlabel .md { font-size: %(small)spx; }
.dbody { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.dbody .sep { color: %(faint)s; }
.dbody .more { color: %(muted)s; }
.foot { left: 36px; bottom: 36px; width: 1350px; height: 39px; font-size: 30px; line-height: 39px; }
"""
SEP = " · "


def week_days(doc, today):
    """``[(day, items, flag, decisions, todos)]`` for today and the six days after.

    Items come from the brief's ``today`` block on its own day and from
    ``this_week`` otherwise; ``flag`` is the week strip's flag for the day
    ("gap", "crunch", ...) or None; ``decisions`` and ``todos`` count what
    lands on the day.
    """
    brief_day = parse_day(doc["date"])
    strip = {w.get("date"): w for w in _dicts(doc.get("week"))}
    todos = _dicts(doc.get("todos"))
    out = []
    for k in range(DAYS):
        day = today + timedelta(days=k)
        if day == brief_day:
            block = doc.get("today") if isinstance(doc.get("today"), dict) else {}
            items = _dicts(block.get("items"))
        else:
            items = week_day(doc, day) or []
        flag = strip.get(day.isoformat(), {}).get("flag")
        flag = flag if isinstance(flag, str) and flag not in ("", "none") else None
        decisions = len(touching(doc.get("decisions"), (day,), "dates"))
        due = len([t for t in todos if t.get("due") == day.isoformat()])
        out.append((day, items, flag, decisions, due))
    return out


def render_week(doc, today, now, tz):
    """pane.html: the week at 1920×1080, for the wall."""
    e = html.escape
    days = week_days(doc, today)
    colours = _colours(doc, [i for d in days for i in d[1]])
    fit = _fit(days)
    rows = []
    for (day, items, flag, decisions, due), shown in zip(days, fit["shown"]):
        parts = []
        for item in items[:shown]:
            time = _time(item)
            parts.append('%s<span class="who" style="--pc: %s">%s</span> %s' % (
                ('<span class="time">%s</span> ' % e(time)) if time else "",
                _colour(item, colours), e(_who(item)), e(_text(item.get("what")))))
        if shown < len(items):
            parts.append('<span class="more">+%d more</span>' % (len(items) - shown))
        body = ('<span class="sep">%s</span>' % SEP).join(parts) or '<span class="none">Nothing on the calendar.</span>'
        rows.append('<div class="day%s%s"><div class="dlabel"><b>%s</b> <span class="md">%s</span></div>'
                    '<div class="dbody">%s%s</div></div>'
                    % (" flagged" if flag else "", " today" if day == today else "",
                       e(_label(day, today)[0]), e(_label(day, today)[1]),
                       _chips(flag, decisions, due), body))
    edition, stale = _edition(doc, parse_day(doc["date"]), today)
    ed, ed_lh = _edition_size(edition, stale)
    css = PANE_CSS % dict(fit["css"], ed=ed, ed_lh=ed_lh, faint=FAINT, muted=MUTED)
    return _page("Family: this week", css, doc, today, now, tz, rows)


def _sizes(body, days):
    """Text sizes from the body size. The day label ("Fri 11/6") is one line, its
    column as wide as the widest label."""
    small = max(FLOOR, round(body * 30 / 31.5, 1))
    label = round(body * 33 / 31.5, 1)
    widest = max(_width([(name, True), (" ", False)], label) + _width([(md, False)], small)
                 for name, md in (_label(d[0], days[0][0]) for d in days))
    return {"body": body, "lh": round(body * 39 / 31.5, 1), "small": small,
            "label": label, "label_w": round(widest + 2, 1)}


def _label(day, today):
    return ("Today" if day == today else day.strftime("%a")), day.strftime("%-m/%-d")


def _fit(days):
    """The largest body size at which every day fits, and how many items each shows.

    Returns ``{"css": {...}, "shown": [n, ...]}``. Below the floor, the day that
    takes the most lines gives up its last item to "+N more" until the week fits.
    """
    shown = [len(d[1]) for d in days]
    for body in [b / 2 for b in range(2 * BIGGEST, 2 * FLOOR - 1, -1)]:
        heights = _heights(body, days, shown)
        if sum(heights) <= WEEK_H - 4:
            return _result(body, days, shown)
    while True:
        heights = _heights(FLOOR, days, shown)
        if sum(heights) <= WEEK_H - 4:
            return _result(FLOOR, days, shown)
        busiest = max((k for k in range(len(days)) if shown[k] > 0),
                      key=lambda k: heights[k], default=None)
        if busiest is None:
            return _result(FLOOR, days, shown)
        shown[busiest] -= 1


def _result(body, days, shown):
    return {"css": dict(_sizes(body, days), week_h=WEEK_H), "shown": list(shown)}


def _heights(body, days, shown):
    s = _sizes(body, days)
    width = DAY_W - s["label_w"] - DAY_GAP
    out = []
    for (day, items, flag, decisions, due), n in zip(days, shown):
        runs = [(chip.replace(" ", "\u00a0") + "\u2002", bold) for chip, bold in _chip_texts(flag, decisions, due)]
        for i, item in enumerate(items[:n]):
            if i:
                runs.append((SEP, False))
            time = _time(item)
            if time:
                runs.append((time + " ", False))
            runs += [(_who(item) + " ", True), (_text(item.get("what")), False)]
        if n < len(items):
            runs.append(((SEP if n else "") + "+%d more" % (len(items) - n), False))
        if not items:
            runs.append(("Nothing on the calendar.", False))
        out.append(_lines(runs, body, width) * s["lh"] + 2 * DAY_PAD + 1.5)
    return out


def _time(item):
    time = _text(item.get("time"))
    return time if time and time != "All day" else ""


def _who(item):
    return _text(item.get("who")) or "Family"


def _page(title, css, doc, today, now, tz, rows):
    e = html.escape
    brief_day = parse_day(doc["date"])
    last = today + timedelta(days=DAYS - 1)
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="brasenia-canvas" content="1920x1080">
<title>%(title)s</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>This week <span>%(range)s</span></h1>%(edition)s</header>
%(rows)s
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {
        "title": e(title), "css": css,
        "range": e("%s – %s" % (today.strftime("%a %-m/%-d"), last.strftime("%a %-m/%-d"))),
        "edition": _edition_html(doc, brief_day, today),
        "rows": '<div class="week">\n%s\n</div>' % "\n".join(rows),
        "foot": e("Family Brief of %s · rendered %s" % (
            brief_day.strftime("%a %-m/%-d"), now.astimezone(tz).strftime("%-I:%M %p"))),
    }


def _edition_html(doc, brief_day, today):
    text, stale = _edition(doc, brief_day, today)
    return '<div class="edition%s">%s</div>' % (" stale" if stale else "", html.escape(text))


def _chip_texts(flag, decisions, due):
    """The day's chips as ``(text, loud)``."""
    chips = []
    if flag:
        chips.append((FLAGS.get(flag, flag), True))
    if decisions:
        chips.append(("%d decision%s" % (decisions, "" if decisions == 1 else "s"), True))
    if due:
        chips.append(("%d due" % due, False))
    return chips


def _chips(flag, decisions, due):
    e = html.escape
    return "".join('<span class="chip%s">%s</span>' % ("" if loud else " quiet", e(text))
                   for text, loud in _chip_texts(flag, decisions, due))


def _colour(item, colours):
    people = _people(item)
    return colours.get(people[0], NEUTRAL) if len(people) == 1 else NEUTRAL


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
