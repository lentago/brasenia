"""The shared page shell and palette of the home and weather panes.

One 1280×720 band (the pane contract): a 60 px header and the 550 px card
area below it fill the 622 px main area inside the 24 px margins, which ends
at y=646, above the bottom-right clock corner. The footer sits bottom-left
and stops 356 px short of the right edge. At 1920×1080 (a desk browser, the
remote's peek) the page zooms 1.5x to fill the screen; the Roku stream
shoots it at 1280×720 and 3x scale.
"""

import html

BG, CARD, LINE = "#0f1518", "#172025", "#2a373e"
TEXT, MUTED, FAINT = "#e4ebee", "#9fb0b8", "#73858e"
GREEN, AMBER, RED, BLUE = "#66bb6a", "#f0a53a", "#ef5350", "#64a8f0"

BASE_CSS = """
html, body { margin: 0; padding: 0; }
@media (min-width: 1900px) and (min-height: 1060px) { html { zoom: 1.5; } }
body { width: 1280px; height: 720px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 21px; line-height: 26px; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px; overflow: hidden; }
header { height: 60px; display: flex; align-items: center; gap: 20px; border-radius: 10px;
  padding: 0 18px; box-sizing: border-box; background: var(--band); }
h1 { margin: 0; font-size: 34px; line-height: 40px; color: #ffffff; white-space: nowrap; }
.summary { margin-left: auto; font-size: 21px; color: var(--band-text); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.card { background: %(card)s; border-radius: 10px; padding: 10px 16px; box-sizing: border-box;
  overflow: hidden; }
h2 { margin: 0; height: 32px; font-size: 21px; line-height: 32px; color: %(muted)s;
  font-weight: normal; white-space: nowrap; }
.ok { color: %(green)s; }
.warn { color: %(amber)s; font-weight: bold; }
.bad { color: %(red)s; font-weight: bold; }
.muted { color: %(muted)s; }
.faint { color: %(faint)s; font-style: italic; }
.none { color: %(faint)s; font-style: italic; }
.foot { position: absolute; left: 24px; bottom: 24px; width: 900px; height: 26px; font-size: 20px;
  line-height: 26px; color: %(faint)s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
""" % {"bg": BG, "text": TEXT, "card": CARD, "muted": MUTED, "faint": FAINT,
       "green": GREEN, "amber": AMBER, "red": RED}


def page(title, band, band_text, css, heading, summary, body, foot):
    """A whole pane page: the header band, ``body`` (HTML) under it, and the footer."""
    e = html.escape
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
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
