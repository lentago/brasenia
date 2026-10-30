"""Render the Family Brief as a document: flowing HTML for a Google Doc (#90).

The panes are fixed 1920×1080 bands for the wall; this is the
same brief as a page that reads top to bottom on a phone. pub imports it into
one Google Doc, updated in place each morning, which is shared beyond the LAN
(kalmia's publish-family-brief). It is built from the same ``latest.json`` as
the panes, so the wall and the Doc can't disagree.

The markup sticks to what Google Docs' HTML import keeps: headings,
paragraphs, bulleted lists, bold, and inline ``color``. Dates are absolute
("Thursday, October 29") rather than "today", so the output depends only on
the brief, not on when it is rendered: a brief that hasn't changed renders
the same bytes.

Sections, each left out when the brief has nothing for it: the day (its
coverage note, then its items), Needs a decision, To do, the rest of the week
(one heading per day, with the week strip's flag), Coming up (``horizon``),
FYI, and the brief's own footer.

``python3 -m family_brief_producer.doc SOURCE`` prints the HTML; SOURCE is a
path, a ``file://`` URL or an ``http://`` URL.
"""

import argparse
import html
import os
import sys
import urllib.parse
from zoneinfo import ZoneInfo

from .document import DocumentError, load, parse_day, parse_ts, urllib_fetch
from .producer import DEFAULT_TZ
from .render import _colours, _people, _text

FLAGS = {"gap": "coverage gap", "crunch": "crunch day"}
INK, MUTED, AMBER, FAINT = "#202124", "#5f6368", "#b06000", "#80868b"
# Google Docs' import drops the browser's default paragraph spacing but keeps
# inline margins, so every paragraph says how much room it wants.
ITEM, LEAD, TITLE, TIGHT = "0 0 6pt 0", "0 0 8pt 0", "12pt 0 2pt 0", "0 0 2pt 0"


def render_doc(doc, tz):
    """The whole document as an HTML page."""
    e = html.escape
    day = parse_day(doc["date"])
    today = _block(doc.get("today"))
    week = [w for w in _dicts(doc.get("this_week")) if _day(w.get("date")) not in (None, day)]
    everything = _dicts(today.get("items")) + [i for w in week for i in _dicts(w.get("items"))] \
        + _dicts(doc.get("horizon"))
    colours = _colours(doc, everything)
    flags = {w.get("date"): w.get("flag") for w in _dicts(doc.get("week"))}

    parts = ['<h1>Family Brief: %s</h1>' % e(_long_date(day))]
    lead = " · ".join(x for x in (_text(doc.get("edition")) or _generated(doc, tz),
                                  _text(doc.get("status_line"))) if x)
    if lead:
        parts.append(_p(lead, MUTED, LEAD))

    parts.append('<h2>%s</h2>' % e(_heading(day, flags)))
    coverage = _text(today.get("coverage"))
    if coverage:
        parts.append('<p style="margin: %s"><b style="color:%s">Coverage:</b> %s</p>' % (LEAD, AMBER, e(coverage)))
    parts.append(_items(_dicts(today.get("items")), colours))

    decisions = _dicts(doc.get("decisions"))
    if decisions:
        parts.append('<h2>Needs a decision</h2>')
        for d in decisions:
            when = _dates(d.get("dates"))
            parts.append('<p style="margin: %s"><b>%s</b>%s</p>' % (
                TITLE, e(_text(d.get("title"))), _span(" · " + when, MUTED) if when else ""))
            if _text(d.get("detail")):
                parts.append('<p style="margin: %s">%s</p>' % (TIGHT, e(_text(d["detail"]))))
            if _text(d.get("source")):
                parts.append(_p("Source: " + _text(d["source"]), FAINT, TIGHT))

    todos = _dicts(doc.get("todos"))
    if todos:
        parts.append('<h2>To do</h2><ul>')
        for t in todos:
            tag = _text(t.get("tag"))
            when = _text(t.get("deadline")) or _dates(t.get("due"))
            parts.append('<li>%s%s%s</li>' % (
                '<b>%s</b> ' % e(tag.capitalize()) if tag else "", e(_text(t.get("text"))),
                _span(" · " + when, MUTED) if when else ""))
        parts.append('</ul>')

    if week:
        parts.append('<h2>The rest of the week</h2>')
        for w in week:
            parts.append('<h3>%s</h3>' % e(_heading(_day(w.get("date")), flags)))
            parts.append(_items(_dicts(w.get("items")), colours))

    horizon = _dicts(doc.get("horizon"))
    if horizon:
        parts.append('<h2>Coming up</h2><ul>')
        for h in horizon:
            line = " · ".join(x for x in (_text(h.get("when")), _text(h.get("what")), _text(h.get("where")))
                              if x)
            parts.append('<li>%s%s%s</li>' % (_who(h, colours), e(line),
                                               _span(" (%s)" % _text(h["note"]), MUTED)
                                               if _text(h.get("note")) else ""))
        parts.append('</ul>')

    fyi = [_text(f) for f in doc.get("fyi") or () if _text(f)] if isinstance(doc.get("fyi"), list) else []
    if fyi:
        parts.append('<h2>FYI</h2><ul>%s</ul>' % "".join('<li>%s</li>' % e(f) for f in fyi))

    footer = " ".join(x for x in (_text(doc.get("footer")), _generated(doc, tz)) if x)
    parts.append(_p(footer, FAINT, TITLE))
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<title>Family Brief</title></head>\n<body style="font-family: Arial, sans-serif; color: %s">\n%s\n'
            '</body></html>\n' % (INK, "\n".join(parts)))


def _items(items, colours):
    """One paragraph per item: the time in bold, who in their colour, what, where, what to bring."""
    if not items:
        return _p("Nothing on the calendar.", FAINT, ITEM)
    e = html.escape
    out = []
    for item in items:
        time = _text(item.get("time")) or "All day"
        rest = e(_text(item.get("what")))
        if _text(item.get("where")):
            rest += _span(" · " + _text(item["where"]), MUTED)
        if item.get("unconfirmed") is True:
            rest += ' <b style="color:%s">(unconfirmed)</b>' % AMBER
        if _text(item.get("bring")):
            rest += _span(" · Bring: " + _text(item["bring"]), MUTED)
        strike = "; text-decoration: line-through" if item.get("cancelled") is True else ""
        out.append('<p style="margin: %s%s"><b>%s</b> · %s%s</p>' % (ITEM, strike, e(time),
                                                                     _who(item, colours), rest))
    return "\n".join(out)


def _who(item, colours):
    """The item's people, bold, in their colour (darkened for a white page) when there is one."""
    who = _text(item.get("who")) or "Family"
    people = _people(item)
    colour = _darken(colours.get(people[0])) if len(people) == 1 and colours.get(people[0]) else INK
    return '<b style="color:%s">%s:</b> ' % (colour, html.escape(who))


def _heading(day, flags):
    flag = flags.get(day.isoformat()) if day else None
    flag = FLAGS.get(flag, flag) if isinstance(flag, str) and flag not in ("", "none") else None
    return _long_date(day) + (" (%s)" % flag if flag else "")


def _dates(value):
    """A date or a list of dates, as "Thu 10/29" or "Thu 10/29, Fri 10/30"."""
    values = value if isinstance(value, list) else [value]
    days = [d for d in (_day(v) for v in values) if d]
    return ", ".join(d.strftime("%a %-m/%-d") for d in days)


def _generated(doc, tz):
    try:
        when = parse_ts(doc.get("generated_at")).astimezone(tz)
    except (TypeError, ValueError, AttributeError):
        return ""
    return "Generated %s at %s." % (_long_date(when.date()), when.strftime("%-I:%M %p"))


def _darken(colour, factor=0.62):
    """A palette colour made dark enough to read on white."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def _p(text, colour, margin):
    return '<p style="margin: %s; color:%s">%s</p>' % (margin, colour, html.escape(text))


def _span(text, colour):
    return '<span style="color:%s">%s</span>' % (colour, html.escape(text))


def _block(value):
    return value if isinstance(value, dict) else {}


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _day(value):
    try:
        return parse_day(value)
    except ValueError:
        return None


def _long_date(day):
    return day.strftime("%A, %B ") + str(day.day)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="family_brief_producer.doc",
                                     description="Print the Family Brief as document HTML (for a Google Doc).")
    parser.add_argument("source", help="latest.json: a path, a file:// URL or an http:// URL")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="the household's time zone (default %(default)s)")
    args = parser.parse_args(argv)
    source = args.source
    if "://" not in source:
        source = "file://" + urllib.parse.quote(os.path.abspath(source))
    try:
        doc = load(urllib_fetch, source)
    except DocumentError as err:
        print("family brief %s" % err, file=sys.stderr)
        return 1
    sys.stdout.write(render_doc(doc, ZoneInfo(args.tz)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
