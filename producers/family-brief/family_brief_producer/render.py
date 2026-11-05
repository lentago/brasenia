"""Render the family pane: one 1920×1080 band (the canvas, ADR-0019), inline CSS, no scripts.

Geometry (all inside the 36 px safe margins): a 90 px header, the two day
columns and the decision strip, with 18 px gaps, fill the 933 px main area
that ends at y=969, above the bottom-right 330×75 px clock corner. The "as
of" footer sits bottom-left and stops short of it.

Nothing is cut short with an ellipsis. Text wraps, and the page picks one
body size for both columns and the strip: the largest on the ladder whose
estimated layout fits the band. A quiet day fills the space with big type;
a busy one comes down toward the floor. The pane has no scripts, so the fit is
worked out here from DejaVu Sans' advance widths (``metrics``), rounded
up. Only when a day does not fit even at the floor does its column end in
"+N more on the board".

The floor is 20 px, below ADR-0019's 30 px, by Chris's call (2026-11-05):
better smaller type than an ellipsis. The ladder only goes under 30 px
when a busy day needs it.

The page declares the 1920×1080 canvas (brasenia ADR-0019), so the Roku stream
renders it at 2x. It is the pane's only rendition: the desk edition is retired.
"""

import html
import re
from datetime import timedelta

from . import metrics
from .document import days, parse_day, touching

MAX_DECISIONS = 2

# Body text sizes tried, largest first. 33 px was the old fixed size.
BIGGEST, FLOOR = 46, 20
MAIN_H, HEADER_H, GAP = 933, 90, 18
COL_W = (1920 - 2 * 36 - GAP) / 2           # 915: two columns share the main width
COL_PAD_X, COL_PAD_Y = 24, 21
ROW_W = COL_W - 2 * COL_PAD_X - 9 - 18      # inside the row's colour bar and padding
ROW_PAD = 7.5
COVER_PAD_X, COVER_PAD_Y = 15, 9
DECIDE_W = 1920 - 2 * 36 - 9 - 2 * 24       # inside the strip's bar and padding
DECIDE_PAD_Y = 12
SLACK = 1.03                                # widths are rounded up by this much

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
  font-size: %(body)spx; line-height: %(lh)spx; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px;
  overflow: hidden; }
header { height: 90px; display: flex; justify-content: space-between;
  align-items: center; gap: 36px; background: %(band)s; border-radius: 15px; padding: 0 27px;
  box-sizing: border-box; }
h1 { margin: 0; font-size: %(h1)spx; line-height: %(h1_lh)spx; color: #ffffff; white-space: nowrap; }
.edition { font-size: %(ed)spx; line-height: %(ed_lh)spx; color: %(band_text)s;
  max-width: 960px; text-align: right; overflow-wrap: anywhere; }
.edition.stale { color: %(amber)s; font-weight: bold; }
.cols { display: flex; gap: 18px; margin-top: 18px; height: %(cols_h)spx; }
.col { flex: 1 1 0; min-width: 0; background: %(card)s; border-radius: 15px;
  padding: 21px 24px; box-sizing: border-box; overflow: hidden; }
h2 { margin: 0 0 12px; font-size: %(h2)spx; line-height: %(h2_lh)spx; white-space: nowrap; }
h2 span { color: %(muted)s; font-weight: normal; font-size: %(body)spx; }
.row { box-sizing: border-box; padding: 7.5px 0 7.5px 18px;
  border-left: 9px solid var(--pc); border-bottom: 1.5px solid %(line)s;
  display: flex; flex-direction: %(row_dir)s; gap: 0 18px; }
.time { flex: %(time_flex)s; font-weight: bold; overflow-wrap: anywhere; }
.what { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.who { font-weight: bold; color: var(--pc); }
.cancelled .time, .cancelled .what { text-decoration: line-through; color: %(muted)s; }
.tag { font-weight: bold; color: %(legacy)s; }
.unconf { font-weight: bold; color: %(amber)s; }
.more { padding: 7.5px 0 7.5px 27px; color: %(muted)s; }
.none { color: %(faint)s; font-style: italic; padding-top: 12px; }
.coverage { box-sizing: border-box; margin-top: 12px; padding: 9px 15px;
  border-radius: 12px; background: %(bg)s; font-size: %(small)spx; line-height: %(small_lh)spx;
  overflow-wrap: anywhere; }
.coverage b { color: %(muted)s; }
.decide { box-sizing: border-box; height: %(decide_h)spx; margin-top: 18px; padding: 12px 24px;
  border-radius: 15px; background: %(amber_wash)s; border-left: 9px solid %(amber)s;
  display: flex; gap: 24px; overflow: hidden; }
.decide .label { flex: 0 0 %(label_w)spx; font-weight: bold; color: %(amber)s;
  font-size: %(small)spx; line-height: %(small_lh)spx; }
.decide ul { flex: 1 1 auto; min-width: 0; margin: 0; padding: 0; list-style: none; }
.decide li { line-height: %(li_lh)spx; overflow-wrap: anywhere; }
.decide li + li { margin-top: 6px; }
.decide .quiet { color: %(muted)s; }
.foot { position: absolute; left: 36px; bottom: 36px; width: 1350px; height: 39px;
  font-size: 30px; line-height: 39px; color: %(faint)s; white-space: nowrap; overflow: hidden; }
"""
COLOURS = {"bg": BG, "card": CARD, "line": LINE, "text": TEXT, "muted": MUTED, "faint": FAINT,
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
    edition, edition_bold = _edition(doc, brief_day, today)
    ed, ed_lh = _edition_size(edition, edition_bold)

    decisions = touching(doc.get("decisions"), (today, tomorrow), "dates")
    lines = _decide_lines(decisions, doc.get("decisions"))
    rows = {"today": [_runs(i) for i in today_items],
            "tomorrow": [_runs(i) for i in tomorrow_items]}
    times = {k: [_text(i.get("time")) or "All day" for i in v]
             for k, v in (("today", today_items), ("tomorrow", tomorrow_items))}
    fit = _fit(rows, times, coverage, lines)

    css = CSS % dict(COLOURS, ed=ed, ed_lh=ed_lh, **fit["css"])
    edition_html = '<div class="edition%s">%s</div>' % (" stale" if edition_bold else "", e(edition))
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
        "css": css,
        "date": e(_long_date(today)),
        "edition": edition_html,
        "today": _column("Today", today, today_items, coverage, colours, fit["shown"]["today"]),
        "tomorrow": _column("Tomorrow", tomorrow, tomorrow_items, None, colours,
                            fit["shown"]["tomorrow"]),
        "decide": _decide(lines),
        "foot": e("Family Brief of %s · rendered %s" % (
            brief_day.strftime("%a %-m/%-d"), now.astimezone(tz).strftime("%-I:%M %p"))),
    }


def _edition(doc, brief_day, today):
    """The header's right side, as ``(text, stale)``: the edition on the brief's own
    day, otherwise an amber note that today's brief has not landed. A brief older
    than yesterday (only ever rendered into the briefing slot) names its date."""
    if brief_day == today:
        return _text(doc.get("edition")) or "Family Brief", False
    if brief_day == today - timedelta(days=1):
        return "No brief yet today: showing %s's" % brief_day.strftime("%A"), True
    return "No brief since %s" % brief_day.strftime("%a %-m/%-d"), True


def _edition_size(text, bold):
    """The largest edition size, 30 px down to the floor, that fits two lines of 960 px."""
    for size in range(30, FLOOR - 1, -1):
        lh = round(size * 1.2, 1)
        if _lines([(text, bold)], size, 960) * lh <= 2 * lh and 2 * lh <= HEADER_H:
            return size, lh
    return FLOOR, round(FLOOR * 1.2, 1)


# --- Fitting -----------------------------------------------------------------

def _sizes(body):
    """Every text size and line height on the page, from the body size."""
    small = max(FLOOR, round(body * 30 / 33, 1))
    h2 = round(body * 42 / 33, 1)
    return {"body": body, "lh": round(body * 39 / 33, 1),
            "small": small, "small_lh": round(small * 1.3, 1),
            "h2": h2, "h2_lh": round(h2 * 51 / 42, 1),
            "li_lh": round(body * 1.25, 1),
            "label_w": round(225 * body / 33, 1),
            # The date never reads smaller than the column headings under it.
            "h1": max(51, min(66, h2 + 6)), "h1_lh": round(max(51, min(66, h2 + 6)) * 1.15, 1)}


def _fit(rows, times, coverage, decisions):
    """Pick the body size, and how many rows each column shows, so the page fits.

    Returns ``{"css": {...}, "shown": {"today": n, "tomorrow": n}}``, where
    ``n`` is how many items the column lists before its "+N more" line.
    """
    everything = {k: len(v) for k, v in rows.items()}
    for body in range(BIGGEST, FLOOR - 1, -1):
        for stacked in (False, True):
            layout = _layout(body, rows, times, coverage, decisions, everything, stacked)
            if layout["fits"]:
                return layout
    # Not even the floor holds everything: drop rows, last first, into "+N more".
    shown = {k: len(v) for k, v in rows.items()}
    while True:
        layout = min((_layout(FLOOR, rows, times, coverage, decisions, shown, stacked)
                      for stacked in (False, True)), key=lambda l: sum(l["over"].values()))
        over = [k for k in ("today", "tomorrow") if layout["over"][k]]
        if not over or all(shown[k] <= 0 for k in over):
            return layout
        for k in over:
            if shown[k] > 0:
                # A "+N more" line replaces at least two rows (it needs one of its own).
                shown[k] = max(0, min(shown[k], len(rows[k])) - (2 if shown[k] == len(rows[k]) else 1))


def _layout(body, rows, times, coverage, decisions, shown, stacked):
    """Estimate the page at ``body`` px. Rows are side by side (time, then what)
    or ``stacked`` (the time on its own line above the what)."""
    s = _sizes(body)
    # The strip: the label beside the decisions, each wrapping in its own width.
    label = _lines([("Needs a decision", True)], s["small"], s["label_w"]) * s["small_lh"]
    ul_w = DECIDE_W - s["label_w"] - 24
    items = sum(_lines([(t, False)], body, ul_w) * s["li_lh"] for t, _ in decisions)
    items += 6 * (len(decisions) - 1)
    decide_h = round(2 * DECIDE_PAD_Y + max(label, items) + 2, 1)
    cols_h = MAIN_H - HEADER_H - GAP - GAP - decide_h

    # Side by side, one time column serves both days, as wide as the widest
    # time, so no time wraps. A time column over 40% of the row is no layout.
    all_times = times["today"][:shown["today"]] + times["tomorrow"][:shown["tomorrow"]]
    widest = max([_width([(t, True)], body) for t in all_times] or [0])
    time_w = round(widest + 2, 1)
    if stacked:
        what_w = ROW_W
    elif time_w > 0.4 * ROW_W:
        return {"fits": False, "over": {"today": True, "tomorrow": True}, "css": {}, "shown": shown}
    else:
        what_w = ROW_W - time_w - 18

    over = {}
    for key in ("today", "tomorrow"):
        h = 2 * COL_PAD_Y + s["h2_lh"] + 12
        n = min(shown[key], len(rows[key]))
        for runs, t in list(zip(rows[key], times[key]))[:n]:
            if stacked:
                lines = _lines([(t, True)], body, ROW_W) + _lines(runs, body, what_w)
            else:
                lines = max(_lines([(t, True)], body, time_w), _lines(runs, body, what_w))
            h += lines * s["lh"] + 2 * ROW_PAD + 1.5
        if n < len(rows[key]) or not rows[key]:
            h += s["lh"] + 2 * ROW_PAD
        if key == "today" and coverage:
            text = [("Coverage: ", True), (coverage, False)]
            h += 12 + 2 * COVER_PAD_Y + _lines(text, s["small"], COL_W - 2 * COL_PAD_X - 2 * COVER_PAD_X) * s["small_lh"]
        over[key] = h > cols_h - 4
    css = dict(s, cols_h=round(cols_h, 1), decide_h=decide_h,
               row_dir="column" if stacked else "row",
               time_flex="0 0 auto" if stacked else "0 0 %spx" % time_w)
    return {"fits": not any(over.values()), "over": over, "css": css, "shown": dict(shown)}


def _width(runs, size):
    return sum(_char_w(ch, bold, size) for text, bold in runs for ch in text)


def _char_w(ch, bold, size):
    table = metrics.BOLD if bold else metrics.REGULAR
    return table.get(ch, metrics.FALLBACK) / metrics.UNITS_PER_EM * size * SLACK


def _lines(runs, size, width):
    """How many lines ``runs`` (``(text, bold)`` pieces) wrap to in ``width`` px.

    Breaks at spaces, as the browser does; a word wider than the line breaks
    anywhere (the CSS says ``overflow-wrap: anywhere``). Trailing spaces hang.
    Widths are rounded up, so this errs toward one line too many.
    """
    chars = [(ch, _char_w(ch, bold, size)) for text, bold in runs for ch in text]
    lines, x, i, n = 1, 0.0, 0, len(chars)
    while i < n:
        j, word = i, 0.0
        while j < n and chars[j][0] != " ":
            word += chars[j][1]
            j += 1
        k, space = j, 0.0
        while k < n and chars[k][0] == " ":
            space += chars[k][1]
            k += 1
        if word > width:
            for _, w in chars[i:j]:
                if x > 0 and x + w > width:
                    lines, x = lines + 1, 0.0
                x += w
        else:
            if x > 0 and x + word > width:
                lines, x = lines + 1, 0.0
            x += word
        x += space
        i = k
    return lines


# --- Markup ------------------------------------------------------------------

def _column(name, day, items, coverage, colours, shown):
    e = html.escape
    rows = [_row(item, colours) for item in items[:shown]]
    extra = len(items) - min(shown, len(items))
    if extra:
        rows.append('<div class="more">+%d more on the board</div>' % extra)
    if not items:
        rows.append('<div class="none">Nothing on the calendar.</div>')
    cover = ('<div class="coverage"><b>Coverage:</b> %s</div>' % e(coverage)) if coverage else ""
    return ('<section class="col">\n<h2>%s <span>%s</span></h2>\n%s\n%s\n</section>'
            % (e(name), e(day.strftime("%a %-m/%-d")), "\n".join(rows), cover))


def _runs(item):
    """An item's text as ``(text, bold)`` pieces, in the order the row shows them."""
    runs = []
    if item.get("unconfirmed") is True:
        runs.append(("▲ ", True))
    if item.get("legacy") is True:
        runs.append(("Legacy ", True))
    who = _text(item.get("who"))
    if who:
        runs.append(("%s: " % who, True))
    runs.append((_what(item), False))
    if _text(item.get("note")):
        runs.append((" - " + _text(item.get("note")), False))
    return runs


def _what(item):
    what = _text(item.get("what"))
    extras = [x for x in (_text(item.get("where")),) if x]
    if _text(item.get("bring")):
        extras.append("bring " + _text(item.get("bring")))
    if extras:
        # A sentence's full stop gives way to the comma that adds the place:
        # "...at the assembly., Harborlight" read badly (#58).
        what = ", ".join(x for x in [what.rstrip(".")] + extras if x)
    return what


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
    bits.append(e(_what(item)))
    if _text(item.get("note")):
        bits.append(" - " + e(_text(item.get("note"))))
    cls = "row cancelled" if item.get("cancelled") is True else "row"
    return ('<div class="%s" style="--pc: %s"><div class="time">%s</div><div class="what">%s</div></div>'
            % (cls, colour, e(_text(item.get("time")) or "All day"), "".join(bits)))


def _decide_lines(decisions, everything):
    """The strip's lines as ``(text, quiet)``."""
    total = len([d for d in everything if isinstance(d, dict)]) if isinstance(everything, list) else 0
    shown = decisions[:MAX_DECISIONS]
    lines = [(_text(d.get("title")), False) for d in shown]
    rest = total - len(shown)
    if not lines:
        lines.append(("Nothing for today or tomorrow.", True))
    if rest > 0 and len(lines) < MAX_DECISIONS:
        lines.append(("%d more on the board" % rest, True))
    return lines


def _decide(lines):
    e = html.escape
    items = ['<li class="quiet">%s</li>' % e(t) if quiet else "<li>%s</li>" % e(t)
             for t, quiet in lines]
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
