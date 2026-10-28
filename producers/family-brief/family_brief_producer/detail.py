"""Render the desk edition: detail.html, one 1920×1080 page, inline CSS, no scripts.

The wall's pane.html is built for reading across a room at 1280×720. This
edition is for a 4K screen read from a desk (the office Roku, ADR-0009): the
same brief with Today's coverage note in full, every decision with its
detail, and the to-do list. It sits beside pane.html in the pane directory;
the compositor reads only pane.html and manifest.json, so the wall never
shows it. A client pins to it by URL.

Geometry, in CSS pixels inside 36 px safe margins: a 64 px header, then two
columns 855 px tall with a 14 px gap. The left column holds Today (480) over
Tomorrow (361); the right holds the decisions (472) over the to-dos (369).
The main area ends at y=969, above the bottom-right clock corner (~330×75,
the wall's 220×50 scaled to 1920). Every list uses fixed-height slots and a
"+N more" last slot, so a busy brief never pushes anything off the page.

The page zooms to its viewport: 2/3 in 1280×720 (the office shooter renders
that at 3x, so this layout lands on 3840×2160 at an effective 2x), 1 at
1920×1080, and 2 at 3840×2160.
"""

import html
from datetime import timedelta

from .document import days, parse_day, touching
from .render import (AMBER, BAND, BAND_TEXT, BG, CARD, FAINT, LEGACY, LINE, MUTED, TEXT,
                     _colours, _long_date, _row, _text)

TODAY_ROWS = 7
TODAY_ROWS_UNDER_COVERAGE = 5
TOMORROW_ROWS = 5
DECISIONS = 5
TODOS = 5

CSS = """
html, body { margin: 0; padding: 0; }
@media (max-width: 1400px) { html { zoom: 0.666667; } }
@media (min-width: 3800px) { html { zoom: 2; } }
body { width: 1920px; height: 1080px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 21px; line-height: 25px; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px;
  overflow: hidden; }
header { height: 64px; display: flex; align-items: center; gap: 24px;
  background: %(band)s; border-radius: 12px; padding: 0 22px; box-sizing: border-box; }
h1 { margin: 0; font-size: 38px; line-height: 44px; color: #ffffff; white-space: nowrap; }
.status { flex: 1 1 auto; min-width: 0; font-size: 22px; color: %(band_text)s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: center; }
.edition { font-size: 22px; color: %(band_text)s; white-space: nowrap; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.grid { display: flex; gap: 16px; margin-top: 14px; height: 855px; }
.stack { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.col { background: %(card)s; border-radius: 12px; padding: 14px 18px;
  box-sizing: border-box; overflow: hidden; }
.today { height: 480px; } .tomorrow { height: 361px; }
.decisions { height: 472px; } .todos { height: 369px; }
h2 { margin: 0 0 8px; height: 36px; font-size: 28px; line-height: 36px; white-space: nowrap; }
h2 span { color: %(muted)s; font-weight: normal; font-size: 22px; }
.row { box-sizing: border-box; height: 56px; padding: 3px 0 3px 12px;
  border-left: 6px solid var(--pc); border-bottom: 1px solid %(line)s;
  display: flex; gap: 14px; overflow: hidden; }
.time { flex: 0 0 160px; font-weight: bold; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.what { flex: 1 1 auto; min-width: 0; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.who { font-weight: bold; color: var(--pc); }
.cancelled .time, .cancelled .what { text-decoration: line-through; color: %(muted)s; }
.tag { font-weight: bold; color: %(legacy)s; }
.unconf { font-weight: bold; color: %(amber)s; }
.more { height: 56px; line-height: 50px; color: %(muted)s; padding-left: 18px; }
.none { color: %(faint)s; font-style: italic; padding-top: 8px; }
.coverage { box-sizing: border-box; height: 87px; margin-top: 8px; padding: 6px 12px;
  border-radius: 8px; background: %(bg)s; font-size: 19px; line-height: 25px;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.coverage b { color: %(muted)s; }
.decision { box-sizing: border-box; height: 80px; padding: 4px 0 4px 12px;
  border-left: 6px solid %(line)s; border-bottom: 1px solid %(line)s; overflow: hidden; }
.decision.near { border-left-color: %(amber)s; }
.dtitle { display: flex; gap: 14px; height: 26px; line-height: 26px; }
.dtitle b { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.when { flex: 0 0 auto; font-size: 19px; color: %(muted)s; white-space: nowrap; }
.near .when { color: %(amber)s; font-weight: bold; }
.detail { font-size: 18px; line-height: 23px; color: %(muted)s; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.todo { box-sizing: border-box; height: 56px; padding: 4px 0 4px 12px;
  border-left: 6px solid %(line)s; border-bottom: 1px solid %(line)s;
  display: flex; gap: 14px; overflow: hidden; }
.todo.near { border-left-color: %(amber)s; }
.ttag { flex: 0 0 110px; font-size: 18px; font-weight: bold; color: %(muted)s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ttext { flex: 1 1 auto; min-width: 0; font-size: 20px; line-height: 24px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.due { flex: 0 0 230px; font-size: 18px; line-height: 24px; color: %(muted)s;
  text-align: right; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.near .due { color: %(amber)s; font-weight: bold; }
.foot { position: absolute; left: 36px; bottom: 30px; width: 1400px; height: 26px;
  font-size: 19px; line-height: 26px; color: %(faint)s; white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "card": CARD, "line": LINE, "text": TEXT, "muted": MUTED, "faint": FAINT,
       "band": BAND, "band_text": BAND_TEXT, "amber": AMBER, "legacy": LEGACY}


def render_detail(doc, today, now, tz):
    """Return detail.html for ``doc`` as seen on ``today`` (a date in the household's zone)."""
    e = html.escape
    tomorrow = today + timedelta(days=1)
    today_items, coverage, tomorrow_items = days(doc, today)
    colours = _colours(doc, today_items + tomorrow_items)

    brief_day = parse_day(doc["date"])
    if brief_day == today:
        edition = '<div class="edition">%s</div>' % e(_text(doc.get("edition")) or "Family Brief")
        status = _text(doc.get("status_line"))
    else:
        edition = ('<div class="edition stale">No brief yet today: showing %s&#39;s</div>'
                   % e(brief_day.strftime("%A")))
        status = ""  # yesterday's counts would read as today's

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Family: today, tomorrow, decisions and to-dos</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>%(date)s</h1><div class="status">%(status)s</div>%(edition)s</header>
<div class="grid">
<div class="stack">
%(today)s
%(tomorrow)s
</div>
<div class="stack">
%(decisions)s
%(todos)s
</div>
</div>
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {
        "css": CSS,
        "date": e(_long_date(today)),
        "status": e(status),
        "edition": edition,
        "today": _day("today", "Today", today, today_items, coverage, colours,
                      TODAY_ROWS_UNDER_COVERAGE if coverage else TODAY_ROWS),
        "tomorrow": _day("tomorrow", "Tomorrow", tomorrow, tomorrow_items, None, colours,
                         TOMORROW_ROWS),
        "decisions": _decisions(doc.get("decisions"), today, tomorrow),
        "todos": _todos(doc.get("todos"), today, tomorrow),
        "foot": e("Family Brief of %s · rendered %s" % (
            brief_day.strftime("%a %-m/%-d"), now.astimezone(tz).strftime("%-I:%M %p"))),
    }


def _fit(entries, slots):
    """The entries that fit ``slots``, and how many a "+N more" last slot stands for."""
    if len(entries) > slots:
        return entries[:slots - 1], len(entries) - (slots - 1)
    return entries, 0


def _day(cls, name, day, items, coverage, colours, slots):
    e = html.escape
    shown, extra = _fit(items, slots)
    rows = [_row(item, colours) for item in shown]
    if extra:
        rows.append('<div class="more">+%d more on the board</div>' % extra)
    if not items:
        rows.append('<div class="none">Nothing on the calendar.</div>')
    cover = ('<div class="coverage"><b>Coverage:</b> %s</div>' % e(coverage)) if coverage else ""
    return ('<section class="col %s">\n<h2>%s <span>%s</span></h2>\n%s\n%s\n</section>'
            % (cls, e(name), e(day.strftime("%a %-m/%-d")), "\n".join(rows), cover))


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _first_date(entry, field):
    """The earliest ISO date in ``field`` (a date or a list of dates), or None."""
    value = entry.get(field)
    values = value if isinstance(value, list) else [value]
    found = []
    for v in values:
        try:
            found.append(parse_day(v))
        except ValueError:
            pass
    return min(found) if found else None


def _by_date(entries, field):
    """Undated entries last; otherwise the brief's own order within a date."""
    far = parse_day("9999-12-31")
    return sorted(entries, key=lambda entry: _first_date(entry, field) or far)


def _decisions(value, today, tomorrow):
    e = html.escape
    entries = _by_date(_dicts(value), "dates")
    near = {id(d) for d in touching(entries, (today, tomorrow), "dates")}
    shown, extra = _fit(entries, DECISIONS)
    rows = []
    for d in shown:
        day = _first_date(d, "dates")
        when = ("Today" if day == today else "Tomorrow" if day == tomorrow
                else day.strftime("%a %-m/%-d") if day else "")
        detail = _text(d.get("detail"))
        rows.append('<div class="decision%s"><div class="dtitle"><b>%s</b><span class="when">%s</span>'
                    '</div>%s</div>'
                    % (" near" if id(d) in near else "", e(_text(d.get("title"))), e(when),
                       '<div class="detail">%s</div>' % e(detail) if detail else ""))
    if extra:
        rows.append('<div class="more">+%d more on the board</div>' % extra)
    if not entries:
        rows.append('<div class="none">No open decisions.</div>')
    return ('<section class="col decisions">\n<h2>Needs a decision <span>%d</span></h2>\n%s\n</section>'
            % (len(entries), "\n".join(rows)))


def _todos(value, today, tomorrow):
    e = html.escape
    entries = _by_date(_dicts(value), "due")
    shown, extra = _fit(entries, TODOS)
    rows = []
    for t in shown:
        due = _first_date(t, "due")
        deadline = _text(t.get("deadline")) or (due.strftime("Due %a %-m/%-d") if due else "")
        rows.append('<div class="todo%s"><div class="ttag">%s</div><div class="ttext">%s</div>'
                    '<div class="due">%s</div></div>'
                    % (" near" if due is not None and due <= tomorrow else "",
                       e(_text(t.get("tag"))), e(_text(t.get("text"))), e(deadline)))
    if extra:
        rows.append('<div class="more">+%d more on the board</div>' % extra)
    if not entries:
        rows.append('<div class="none">Nothing to do.</div>')
    return ('<section class="col todos">\n<h2>To do <span>%d</span></h2>\n%s\n</section>'
            % (len(entries), "\n".join(rows)))
