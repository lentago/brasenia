"""Render the family pane: one 1280×720 band, inline CSS, no scripts.

Geometry (all inside the 24 px safe margins): a 60 px header, two day
columns 452 px tall, and an 86 px decision strip, with 12 px gaps, add up to
the 622 px main area that ends at y=646, above the bottom-right 220×50 px
clock corner. The "as of" footer sits bottom-left and stops short of it.

Rows are fixed-height slots (62 px, two lines of text at most), so a busy day
never pushes anything off the band: a column shows ROWS slots, or one fewer
under the coverage callout, and the last slot becomes "+N more" when the day
has more items than fit.

At 1920×1080 (a Cast receiver's iframe on an HD set) the page zooms 1.5x, so
the same band fills the screen; the Roku shooter renders it at 1280×720.
"""

import html
import re
from datetime import timedelta

from .document import days, parse_day, touching

ROWS = 6
ROWS_UNDER_COVERAGE = 5
MAX_DECISIONS = 2

BG, CARD, LINE = "#0f1518", "#172025", "#2a373e"
TEXT, MUTED, FAINT = "#e4ebee", "#9fb0b8", "#73858e"
BAND, BAND_TEXT = "#173a2b", "#c7ead3"
AMBER, AMBER_WASH = "#f0a53a", "#2b2214"
LEGACY = "#7e57c2"
# Used in order of first appearance when the document carries no "people" legend.
PALETTE = ("#66bb6a", "#a48ce0", "#64a8f0", "#f06292", "#ffb74d", "#4dd0e1")
NEUTRAL = "#90a4ae"
HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")

CSS = """
html, body { margin: 0; padding: 0; }
@media (min-width: 1900px) and (min-height: 1060px) { html { zoom: 1.5; } }
body { width: 1280px; height: 720px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 22px; line-height: 26px; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px;
  overflow: hidden; }
header { height: 60px; display: flex; justify-content: space-between;
  align-items: center; background: %(band)s; border-radius: 10px; padding: 0 18px;
  box-sizing: border-box; }
h1 { margin: 0; font-size: 34px; line-height: 40px; color: #ffffff; white-space: nowrap; }
.edition { font-size: 20px; color: %(band_text)s; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 640px; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.cols { display: flex; gap: 12px; margin-top: 12px; height: 452px; }
.col { flex: 1 1 0; min-width: 0; background: %(card)s; border-radius: 10px;
  padding: 14px 16px; box-sizing: border-box; overflow: hidden; }
h2 { margin: 0 0 8px; height: 34px; font-size: 28px; line-height: 34px; white-space: nowrap; }
h2 span { color: %(muted)s; font-weight: normal; font-size: 22px; }
.row { box-sizing: border-box; height: 62px; padding: 5px 0 5px 12px;
  border-left: 6px solid var(--pc); border-bottom: 1px solid %(line)s;
  display: flex; gap: 12px; overflow: hidden; }
.time { flex: 0 0 150px; font-weight: bold; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.what { flex: 1 1 auto; min-width: 0; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.who { font-weight: bold; color: var(--pc); }
.cancelled .time, .cancelled .what { text-decoration: line-through; color: %(muted)s; }
.tag { font-weight: bold; color: %(legacy)s; }
.unconf { font-weight: bold; color: %(amber)s; }
.more { height: 62px; line-height: 52px; color: %(muted)s; padding-left: 18px; }
.none { color: %(faint)s; font-style: italic; padding-top: 8px; }
.coverage { box-sizing: border-box; height: 64px; margin-top: 8px; padding: 6px 10px;
  border-radius: 8px; background: %(bg)s; font-size: 20px; line-height: 26px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.coverage b { color: %(muted)s; }
.decide { box-sizing: border-box; height: 86px; margin-top: 12px; padding: 8px 16px;
  border-radius: 10px; background: %(amber_wash)s; border-left: 6px solid %(amber)s;
  display: flex; gap: 16px; overflow: hidden; }
.decide .label { flex: 0 0 150px; font-weight: bold; color: %(amber)s; font-size: 20px;
  line-height: 26px; }
.decide ul { flex: 1 1 auto; min-width: 0; margin: 0; padding: 0; list-style: none; }
.decide li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; height: 35px;
  line-height: 35px; }
.decide .quiet { color: %(muted)s; }
.foot { position: absolute; left: 24px; bottom: 24px; width: 900px; height: 26px;
  font-size: 20px; line-height: 26px; color: %(faint)s; white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "card": CARD, "line": LINE, "text": TEXT, "muted": MUTED, "faint": FAINT,
       "band": BAND, "band_text": BAND_TEXT, "amber": AMBER, "amber_wash": AMBER_WASH,
       "legacy": LEGACY}


def render(doc, today, now, tz):
    """Return pane.html for ``doc`` as seen on ``today`` (a date in the household's zone).

    ``now`` is the render time (aware) and ``tz`` the household's zone, used
    for the footer's clock time.
    """
    e = html.escape
    tomorrow = today + timedelta(days=1)
    today_items, coverage, tomorrow_items = days(doc, today)
    colours = _colours(doc, today_items + tomorrow_items)

    brief_day = parse_day(doc["date"])
    if brief_day == today:
        edition = '<div class="edition">%s</div>' % e(_text(doc.get("edition")) or "Family Brief")
    else:
        edition = ('<div class="edition stale">No brief yet today: showing %s&#39;s</div>'
                   % e(brief_day.strftime("%A")))

    decisions = touching(doc.get("decisions"), (today, tomorrow), "dates")
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Family: today and tomorrow</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>%(date)s</h1>%(edition)s</header>
<div class="cols">
%(today)s
%(tomorrow)s
</div>
%(decide)s
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {
        "css": CSS,
        "date": e(_long_date(today)),
        "edition": edition,
        "today": _column("Today", today, today_items, coverage, colours),
        "tomorrow": _column("Tomorrow", tomorrow, tomorrow_items, None, colours),
        "decide": _decide(decisions, doc.get("decisions")),
        "foot": e("Family Brief of %s · rendered %s" % (
            brief_day.strftime("%a %-m/%-d"), now.astimezone(tz).strftime("%-I:%M %p"))),
    }


def _column(name, day, items, coverage, colours):
    e = html.escape
    slots = ROWS_UNDER_COVERAGE if coverage else ROWS
    if len(items) > slots:
        shown, extra = items[:slots - 1], len(items) - (slots - 1)
    else:
        shown, extra = items, 0
    rows = [_row(item, colours) for item in shown]
    if extra:
        rows.append('<div class="more">+%d more on the board</div>' % extra)
    if not items:
        rows.append('<div class="none">Nothing on the calendar.</div>')
    cover = ('<div class="coverage"><b>Coverage:</b> %s</div>' % e(coverage)) if coverage else ""
    return ('<section class="col">\n<h2>%s <span>%s</span></h2>\n%s\n%s\n</section>'
            % (e(name), e(day.strftime("%a %-m/%-d")), "\n".join(rows), cover))


def _row(item, colours):
    e = html.escape
    people = _people(item)
    colour = colours.get(people[0], NEUTRAL) if len(people) == 1 else NEUTRAL
    bits = []
    if item.get("unconfirmed") is True:
        bits.append('<span class="unconf">▲</span> ')
    if item.get("legacy") is True:
        bits.append('<span class="tag">Legacy</span> ')
    who = _text(item.get("who"))
    if who:
        bits.append('<span class="who">%s:</span> ' % e(who))
    what = _text(item.get("what"))
    extras = [x for x in (_text(item.get("where")),) if x]
    if _text(item.get("bring")):
        extras.append("bring " + _text(item.get("bring")))
    bits.append(e(what + (", " + ", ".join(extras) if extras else "")))
    if _text(item.get("note")):
        bits.append(" - " + e(_text(item.get("note"))))
    cls = "row cancelled" if item.get("cancelled") is True else "row"
    return ('<div class="%s" style="--pc: %s"><div class="time">%s</div><div class="what">%s</div></div>'
            % (cls, colour, e(_text(item.get("time")) or "All day"), "".join(bits)))


def _decide(decisions, everything):
    e = html.escape
    total = len([d for d in everything if isinstance(d, dict)]) if isinstance(everything, list) else 0
    shown = decisions[:MAX_DECISIONS]
    items = ["<li>%s</li>" % e(_text(d.get("title"))) for d in shown]
    rest = total - len(shown)
    if not items:
        items.append('<li class="quiet">Nothing for today or tomorrow.</li>')
    if rest > 0 and len(items) < MAX_DECISIONS:
        items.append('<li class="quiet">%d more on the board</li>' % rest)
    return ('<div class="decide"><div class="label">Needs a decision</div><ul>%s</ul></div>'
            % "".join(items))


def _colours(doc, items):
    """Person key → colour: the document's ``people`` legend first, then the palette."""
    out = {}
    legend = doc.get("people")
    if isinstance(legend, dict):
        for key, entry in legend.items():
            colour = entry.get("color") if isinstance(entry, dict) else None
            if isinstance(colour, str) and HEX.match(colour):
                out[key] = colour
    spare = [c for c in PALETTE if c not in out.values()]
    for item in items:
        for key in _people(item):
            if key not in out:
                out[key] = spare.pop(0) if spare else NEUTRAL
    return out


def _people(item):
    """An item's person keys; anything but a list of strings counts as none."""
    people = item.get("people")
    return [p for p in people if isinstance(p, str)] if isinstance(people, list) else []


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _long_date(day):
    return day.strftime("%A, %B ") + str(day.day)
