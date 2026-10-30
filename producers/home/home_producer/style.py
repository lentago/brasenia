"""The shared page shell and palette of the home and weather panes.

One 1920×1080 band (the pane contract): a 90 px header and the 825 px card
area below it fill the 933 px main area inside the 36 px margins, which ends
at y=969, above the bottom-right clock corner. The footer sits bottom-left
and stops 534 px short of the right edge. It declares the 1920×1080 canvas
(lentago/brasenia ADR-0019), so the Roku stream renders it at 2x scale.
"""

import html

BG, CARD, LINE = "#0f1518", "#172025", "#2a373e"
TEXT, MUTED, FAINT = "#e4ebee", "#9fb0b8", "#73858e"
GREEN, AMBER, RED, BLUE = "#66bb6a", "#f0a53a", "#ef5350", "#64a8f0"

BASE_CSS = """
html, body { margin: 0; padding: 0; }
body { width: 1920px; height: 1080px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 31.5px; line-height: 39px; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px; overflow: hidden; }
header { height: 90px; display: flex; align-items: center; gap: 30px; border-radius: 15px;
  padding: 0 27px; box-sizing: border-box; background: var(--band); }
h1 { margin: 0; font-size: 51px; line-height: 60px; color: #ffffff; white-space: nowrap; }
.summary { margin-left: auto; font-size: 31.5px; color: var(--band-text); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.card { background: %(card)s; border-radius: 15px; padding: 15px 24px; box-sizing: border-box;
  overflow: hidden; }
h2 { margin: 0; height: 48px; font-size: 31.5px; line-height: 48px; color: %(muted)s;
  font-weight: normal; white-space: nowrap; }
.ok { color: %(green)s; }
.warn { color: %(amber)s; font-weight: bold; }
.bad { color: %(red)s; font-weight: bold; }
.muted { color: %(muted)s; }
.faint { color: %(faint)s; font-style: italic; }
.none { color: %(faint)s; font-style: italic; }
.foot { position: absolute; left: 36px; bottom: 36px; width: 1350px; height: 39px; font-size: 30px;
  line-height: 39px; color: %(faint)s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
""" % {"bg": BG, "text": TEXT, "card": CARD, "muted": MUTED, "faint": FAINT,
       "green": GREEN, "amber": AMBER, "red": RED}


def page(title, band, band_text, css, heading, summary, body, foot):
    """A whole pane page: the header band, ``body`` (HTML) under it, and the footer."""
    e = html.escape
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="brasenia-canvas" content="1920x1080">
<title>%(title)s</title>
<style>%(css)s</style></head>
<body style="--band: %(band)s; --band-text: %(band_text)s">
<div class="main">
<header><h1>%(heading)s</h1><div class="summary">%(summary)s</div></header>
%(body)s
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {"title": e(title), "css": BASE_CSS + css, "band": band, "band_text": band_text,
       "heading": heading, "summary": summary, "body": body, "foot": e(foot)}


def allot(needs, budget):
    """Share ``budget`` rows among groups needing ``needs`` rows each.

    Small groups get all they need; what is left is split evenly among the
    rest (water-filling), so one long list can't push the others off the band.
    """
    out = [0] * len(needs)
    left, order = budget, sorted(range(len(needs)), key=lambda i: needs[i])
    for k, i in enumerate(order):
        share = left // (len(order) - k)
        out[i] = min(needs[i], share)
        left -= out[i]
    return out


def clock(dt, tz):
    return dt.astimezone(tz).strftime("%-I:%M %p")


def degrees(value):
    """A temperature as a whole number of degrees ("44°"), or "–" when unknown."""
    try:
        return "%d°" % whole(float(value))
    except (TypeError, ValueError):
        return "–"


def whole(x):
    # half away from zero, as a reader expects (Python's round() is banker's)
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)
