"""Render the family week: panes/family-week/{pane.html, detail.html}.

The Family Brief's seven days from today, one row per day: the day, any
coverage flag the brief raised for it (a gap, a crunch), how many decisions
and to-dos land on it, and its items. ``render_week`` is the wall's 1280×720
cut (each day's items on two lines at most); ``render_week_detail`` is the
1920×1080 desk edition (times, and up to six items a day), which zooms to its
viewport like ``detail.html``. Both are resting panes (``ambient``) the
household can make the default from the Roku remote (#83).
"""

import html
from datetime import timedelta

from .document import parse_day, touching, week_day
from .render import (AMBER, BAND, BAND_TEXT, BG, CARD, FAINT, LINE, MUTED, NEUTRAL, TEXT,
                     _colours, _edition, _people, _text)

DAYS = 7
FLAGS = {"gap": "coverage gap", "crunch": "crunch day"}
DETAIL_ITEMS = 6

BASE_CSS = """
html, body { margin: 0; padding: 0; }
body { overflow: hidden; position: relative; background: %(bg)s; color: %(text)s;
  font-family: "DejaVu Sans", sans-serif; }
header { display: flex; align-items: center; gap: 20px; background: %(band)s;
  box-sizing: border-box; }
h1 { margin: 0; color: #ffffff; white-space: nowrap; }
h1 span { color: %(band_text)s; font-weight: normal; }
.edition { margin-left: auto; color: %(band_text)s; white-space: nowrap; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.day { box-sizing: border-box; display: flex; border-left: 6px solid %(line)s;
  border-bottom: 1px solid %(line)s; background: %(card)s; overflow: hidden; }
.day.flagged { border-left-color: %(amber)s; }
.day.today { background: #1d2a30; }
.dlabel { flex: 0 0 auto; }
.dlabel b { display: block; }
.dlabel .md { color: %(muted)s; }
.chip { display: inline-block; margin-right: 10px; color: %(amber)s; font-weight: bold; white-space: nowrap; }
.chip.quiet { color: %(muted)s; font-weight: normal; }
.who { font-weight: bold; color: var(--pc); }
.time { color: %(muted)s; }
.none { color: %(faint)s; font-style: italic; }
.foot { position: absolute; color: %(faint)s; white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "text": TEXT, "band": BAND, "band_text": BAND_TEXT, "amber": AMBER,
       "line": LINE, "card": CARD, "muted": MUTED, "faint": FAINT}

# The wall cut, 1280×720 CSS: a 60 px header and seven 78 px day rows fill the
# 622 px main area, which ends at y=646 above the clock corner.
PANE_CSS = BASE_CSS + """
@media (min-width: 1900px) and (min-height: 1060px) { html { zoom: 1.5; } }
body { width: 1280px; height: 720px; font-size: 21px; line-height: 26px; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px; overflow: hidden; }
header { height: 60px; border-radius: 10px; padding: 0 18px; margin-bottom: 12px; }
h1 { font-size: 32px; line-height: 40px; }
h1 span { font-size: 22px; }
.edition { font-size: 20px; }
.day { height: 78px; padding: 6px 12px; gap: 14px; }
.dlabel { width: 112px; font-size: 22px; line-height: 30px; }
.dlabel .md { font-size: 20px; }
.dbody { flex: 1 1 auto; min-width: 0; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.dbody .sep { color: %(faint)s; }
.foot { left: 24px; bottom: 24px; width: 900px; height: 26px; font-size: 20px; line-height: 26px; }
""" % {"faint": FAINT}

# The desk edition, 1920×1080 CSS inside 36 px margins: a 64 px header, a
# 14 px gap and seven 120 px rows end at y=974, clear of the clock corner
# (~330×75 at the bottom right) on the right, where rows leave room.
DETAIL_CSS = BASE_CSS + """
@media (max-width: 1400px) { html { zoom: 0.666667; } }
@media (min-width: 3800px) { html { zoom: 2; } }
body { width: 1920px; height: 1080px; font-size: 20px; line-height: 26px; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 938px; overflow: hidden; }
header { height: 64px; border-radius: 12px; padding: 0 22px; margin-bottom: 14px; }
h1 { font-size: 38px; line-height: 44px; }
h1 span { font-size: 24px; }
.edition { font-size: 22px; }
.day { height: 120px; padding: 10px 16px; gap: 20px; }
.dlabel { width: 210px; font-size: 26px; line-height: 32px; }
.dlabel .md { font-size: 20px; line-height: 26px; }
.dlabel .chip { display: block; font-size: 18px; line-height: 24px; }
.items { flex: 1 1 auto; min-width: 0; display: grid; grid-template-columns: repeat(3, 1fr);
  grid-auto-rows: 50px; column-gap: 18px; overflow: hidden; }
.item { min-width: 0; padding-left: 10px; border-left: 4px solid var(--pc); font-size: 19px;
  line-height: 24px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; }
.item.cancelled { text-decoration: line-through; color: %(muted)s; }
.more { color: %(muted)s; font-size: 19px; line-height: 50px; }
.foot { left: 36px; bottom: 30px; width: 1400px; height: 26px; font-size: 19px; line-height: 26px; }
""" % {"muted": MUTED}


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
    """pane.html: the week at 1280×720, for the wall."""
    e = html.escape
    days = week_days(doc, today)
    colours = _colours(doc, [i for d in days for i in d[1]])
    rows = []
    for day, items, flag, decisions, due in days:
        parts = []
        for item in items:
            colour = _colour(item, colours)
            time = _text(item.get("time"))
            parts.append('%s<span class="who" style="--pc: %s">%s</span> %s' % (
                ('<span class="time">%s</span> ' % e(time)) if time and time != "All day" else "",
                colour, e(_text(item.get("who")) or "Family"), e(_text(item.get("what")))))
        body = '<span class="sep"> · </span>'.join(parts) or '<span class="none">Nothing on the calendar.</span>'
        rows.append('<div class="day%s%s"><div class="dlabel"><b>%s</b><span class="md">%s</span></div>'
                    '<div class="dbody">%s%s</div></div>'
                    % (" flagged" if flag else "", " today" if day == today else "",
                       e("Today" if day == today else day.strftime("%a")), e(day.strftime("%-m/%-d")),
                       _chips(flag, decisions, due), body))
    return _page("Family: this week", PANE_CSS, doc, today, now, tz, rows)


def render_week_detail(doc, today, now, tz):
    """detail.html: the week at 1920×1080, the desk edition."""
    e = html.escape
    days = week_days(doc, today)
    colours = _colours(doc, [i for d in days for i in d[1]])
    rows = []
    for day, items, flag, decisions, due in days:
        shown, extra = (items[:DETAIL_ITEMS - 1], len(items) - (DETAIL_ITEMS - 1)) \
            if len(items) > DETAIL_ITEMS else (items, 0)
        cells = []
        for item in shown:
            time = _text(item.get("time")) or "All day"
            cells.append('<div class="item%s" style="--pc: %s"><span class="time">%s</span> '
                         '<span class="who">%s:</span> %s</div>'
                         % (" cancelled" if item.get("cancelled") is True else "", _colour(item, colours),
                            e(time), e(_text(item.get("who")) or "Family"), e(_text(item.get("what")))))
        if extra:
            cells.append('<div class="more">+%d more on the board</div>' % extra)
        if not items:
            cells.append('<div class="none">Nothing on the calendar.</div>')
        rows.append('<div class="day%s%s"><div class="dlabel"><b>%s</b><span class="md">%s</span>%s</div>'
                    '<div class="items">%s</div></div>'
                    % (" flagged" if flag else "", " today" if day == today else "",
                       e("Today" if day == today else day.strftime("%A")), e(day.strftime("%-m/%-d")),
                       _chips(flag, decisions, due), "".join(cells)))
    return _page("Family: this week", DETAIL_CSS, doc, today, now, tz, rows)


def _page(title, css, doc, today, now, tz, rows):
    e = html.escape
    brief_day = parse_day(doc["date"])
    last = today + timedelta(days=DAYS - 1)
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
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
        "edition": _edition(doc, brief_day, today),
        "rows": "\n".join(rows),
        "foot": e("Family Brief of %s · rendered %s" % (
            brief_day.strftime("%a %-m/%-d"), now.astimezone(tz).strftime("%-I:%M %p"))),
    }


def _chips(flag, decisions, due):
    e = html.escape
    chips = []
    if flag:
        chips.append('<span class="chip">%s</span>' % e(FLAGS.get(flag, flag)))
    if decisions:
        chips.append('<span class="chip">%d decision%s</span>' % (decisions, "" if decisions == 1 else "s"))
    if due:
        chips.append('<span class="chip quiet">%d due</span>' % due)
    return "".join(chips)


def _colour(item, colours):
    people = _people(item)
    return colours.get(people[0], NEUTRAL) if len(people) == 1 else NEUTRAL


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
