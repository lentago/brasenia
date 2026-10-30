"""Render the family pane: one 1920×1080 band (the canvas, ADR-0019), inline CSS, no scripts.

Geometry (all inside the 36 px safe margins): a 90 px header, two day
columns 678 px tall, and a 129 px decision strip, with 18 px gaps, add up to
the 933 px main area that ends at y=969, above the bottom-right 330×75 px
clock corner. The "as of" footer sits bottom-left and stops short of it.

Rows are fixed-height slots (93 px, two lines of text at most), so a busy day
never pushes anything off the band: a column shows ROWS slots, or one fewer
under the coverage callout, and the last slot becomes "+N more" when the day
has more items than fit.

The page declares the 1920×1080 canvas (brasenia ADR-0019), so the Roku stream
renders it at 2x. It is the pane's only rendition: the desk edition is retired.
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
body { width: 1920px; height: 1080px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 33px; line-height: 39px; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px;
  overflow: hidden; }
header { height: 90px; display: flex; justify-content: space-between;
  align-items: center; background: %(band)s; border-radius: 15px; padding: 0 27px;
  box-sizing: border-box; }
h1 { margin: 0; font-size: 51px; line-height: 60px; color: #ffffff; white-space: nowrap; }
.edition { font-size: 30px; color: %(band_text)s; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 960px; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.cols { display: flex; gap: 18px; margin-top: 18px; height: 678px; }
.col { flex: 1 1 0; min-width: 0; background: %(card)s; border-radius: 15px;
  padding: 21px 24px; box-sizing: border-box; overflow: hidden; }
h2 { margin: 0 0 12px; height: 51px; font-size: 42px; line-height: 51px; white-space: nowrap; }
h2 span { color: %(muted)s; font-weight: normal; font-size: 33px; }
.row { box-sizing: border-box; height: 93px; padding: 7.5px 0 7.5px 18px;
  border-left: 9px solid var(--pc); border-bottom: 1.5px solid %(line)s;
  display: flex; gap: 18px; overflow: hidden; }
.time { flex: 0 0 225px; font-weight: bold; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.what { flex: 1 1 auto; min-width: 0; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.who { font-weight: bold; color: var(--pc); }
.cancelled .time, .cancelled .what { text-decoration: line-through; color: %(muted)s; }
.tag { font-weight: bold; color: %(legacy)s; }
.unconf { font-weight: bold; color: %(amber)s; }
.more { height: 93px; line-height: 78px; color: %(muted)s; padding-left: 27px; }
.none { color: %(faint)s; font-style: italic; padding-top: 12px; }
.coverage { box-sizing: border-box; height: 96px; margin-top: 12px; padding: 9px 15px;
  border-radius: 12px; background: %(bg)s; font-size: 30px; line-height: 39px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.coverage b { color: %(muted)s; }
.decide { box-sizing: border-box; height: 129px; margin-top: 18px; padding: 12px 24px;
  border-radius: 15px; background: %(amber_wash)s; border-left: 9px solid %(amber)s;
  display: flex; gap: 24px; overflow: hidden; }
.decide .label { flex: 0 0 225px; font-weight: bold; color: %(amber)s; font-size: 30px;
  line-height: 39px; }
.decide ul { flex: 1 1 auto; min-width: 0; margin: 0; padding: 0; list-style: none; }
.decide li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; height: 52.5px;
  line-height: 52.5px; }
.decide .quiet { color: %(muted)s; }
.foot { position: absolute; left: 36px; bottom: 36px; width: 1350px; height: 39px;
  font-size: 30px; line-height: 39px; color: %(faint)s; white-space: nowrap; overflow: hidden; }
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
    edition = _edition(doc, brief_day, today)

    decisions = touching(doc.get("decisions"), (today, tomorrow), "dates")
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="brasenia-canvas" content="1920x1080">
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


def _edition(doc, brief_day, today):
    """The header's right side: the edition on the brief's own day, otherwise
    an amber note that today's brief has not landed. A brief older than
    yesterday (only ever rendered into the briefing slot) names its date."""
    e = html.escape
    if brief_day == today:
        return '<div class="edition">%s</div>' % e(_text(doc.get("edition")) or "Family Brief")
    if brief_day == today - timedelta(days=1):
        return ('<div class="edition stale">No brief yet today: showing %s&#39;s</div>'
                % e(brief_day.strftime("%A")))
    return '<div class="edition stale">No brief since %s</div>' % e(brief_day.strftime("%a %-m/%-d"))


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
    if extras:
        # A sentence's full stop gives way to the comma that adds the place:
        # "...at the assembly., Harborlight" read badly (#58).
        what = ", ".join(x for x in [what.rstrip(".")] + extras if x)
    bits.append(e(what))
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
