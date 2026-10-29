"""Render the fleet pane: one 1280×720 band, inline CSS, no scripts.

Geometry (inside the 24 px margins): a 60 px header, a 96 px row of five
counts, and a 442 px row of three cards, with 12 px gaps, fill the 622 px
main area that ends at y=646, above the bottom-right 220×50 px clock corner.
The footer sits bottom-left and stops 356 px short of the right edge.

The cards are Workers (one 38 px row each: idle, busy with a project, or
silent when its heartbeat stopped), Last 24 hours (the six most recent runs,
two 58 px lines each) and Agent PRs (oldest first, the same two-line rows).
Only counts, project names, models and PR titles appear: no prompt, no log.
"""

import html

BG, CARD, LINE = "#0f1518", "#172025", "#2a373e"
TEXT, MUTED, FAINT = "#e4ebee", "#9fb0b8", "#73858e"
BAND, BAND_TEXT = "#2b2545", "#dcd3f5"
GREEN, AMBER, RED, BLUE = "#66bb6a", "#f0a53a", "#ef5350", "#64a8f0"
CARD_H, CHROME, ROW_H, ROW2_H = 442, 52, 38, 58

CSS = """
html, body { margin: 0; padding: 0; }
@media (min-width: 1900px) and (min-height: 1060px) { html { zoom: 1.5; } }
body { width: 1280px; height: 720px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 21px; line-height: 26px; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px; overflow: hidden; }
header { height: 60px; display: flex; align-items: center; gap: 20px; border-radius: 10px;
  padding: 0 18px; box-sizing: border-box; background: %(band)s; }
h1 { margin: 0; font-size: 34px; line-height: 40px; color: #ffffff; white-space: nowrap; }
h1 span { font-size: 22px; font-weight: normal; color: %(band_text)s; }
.summary { margin-left: auto; font-size: 20px; color: %(amber)s; white-space: nowrap; }
.tiles { display: flex; gap: 12px; margin-top: 12px; height: 96px; }
.tile { flex: 1 1 0; min-width: 0; background: %(card)s; border-radius: 10px; padding: 8px 16px;
  box-sizing: border-box; }
.tile .n { height: 48px; font-size: 40px; line-height: 48px; font-weight: bold; }
.tile .l { height: 26px; font-size: 20px; color: %(muted)s; white-space: nowrap; }
.cols { display: flex; gap: 12px; margin-top: 12px; height: 442px; }
.card { background: %(card)s; border-radius: 10px; padding: 10px 16px; box-sizing: border-box;
  overflow: hidden; height: 442px; }
.card.workers { flex: 0 0 360px; }
.card.runs { flex: 0 0 420px; }
.card.prs { flex: 1 1 auto; min-width: 0; }
h2 { margin: 0; height: 32px; font-size: 21px; line-height: 32px; color: %(muted)s;
  font-weight: normal; white-space: nowrap; }
.row { height: 38px; box-sizing: border-box; display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid %(line)s; }
.row2 { height: 58px; box-sizing: border-box; padding: 3px 0; border-bottom: 1px solid %(line)s; }
.row2 > div { height: 26px; display: flex; gap: 12px; }
.name { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.right { flex: 0 0 auto; white-space: nowrap; }
.row2 > .sub { display: block; color: %(muted)s; font-size: 20px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.busy { color: %(blue)s; font-weight: bold; }
.ok { color: %(green)s; }
.warn { color: %(amber)s; font-weight: bold; }
.bad { color: %(red)s; font-weight: bold; }
.muted { color: %(muted)s; }
.none { color: %(faint)s; font-style: italic; padding-top: 6px; }
.foot { position: absolute; left: 24px; bottom: 24px; width: 900px; height: 26px; font-size: 20px;
  line-height: 26px; color: %(faint)s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
""" % {"bg": BG, "text": TEXT, "card": CARD, "line": LINE, "muted": MUTED, "faint": FAINT,
       "band": BAND, "band_text": BAND_TEXT, "green": GREEN, "amber": AMBER, "red": RED, "blue": BLUE}


def render(snap, prs, now, tz):
    """pane.html. ``prs`` is ``{"total", "items", "as_of", "error"}``, or None before the first search."""
    e = html.escape
    runs = snap["runs"]
    failed = sum(1 for r in runs if r["exit"] != 0)
    tiles = "".join('<div class="tile"><div class="n%s">%d</div><div class="l">%s</div></div>'
                    % (cls, n, e(label)) for n, label, cls in (
                        (snap["alive"], "workers alive", "" if snap["alive"] else " bad"),
                        (snap["busy"], "busy", " busy" if snap["busy"] else ""),
                        (snap["waiting"], "waiting", " warn" if snap["waiting"] else ""),
                        (len(runs), "runs, 24 h", ""),
                        (failed, "failed, 24 h", " bad" if failed else "")))
    stale = prs is not None and prs.get("error") and prs.get("as_of") is not None
    summary = "agent PRs as of %s" % _clock(prs["as_of"], tz) if stale else ""
    foot = "claude-jobs queue · as of %s" % _clock(now, tz)
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Fleet</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>Fleet <span>the bullpen</span></h1><div class="summary">%(summary)s</div></header>
<div class="tiles">%(tiles)s</div>
<div class="cols">%(workers)s%(runs)s%(prs)s</div>
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {"css": CSS, "summary": e(summary), "tiles": tiles, "workers": _workers(snap, now),
       "runs": _runs(runs, tz), "prs": _prs(prs, now), "foot": e(foot)}


def _workers(snap, now):
    e = html.escape
    rows = []
    for w in snap["workers"][:(CARD_H - CHROME) // ROW_H]:
        if w["state"] == "busy":
            what = w["project"] or "ad hoc"
            state = '<span class="busy">%s</span>%s' % (
                e(what), " · " + _age(now, w["since"]) if w["since"] else "")
        elif w["state"] == "idle":
            state = '<span class="muted">idle</span>'
        else:
            state = '<span class="bad">silent %s</span>' % _age(now, w["since"])
        rows.append('<div class="row"><span class="name">%s</span><span class="right">%s</span></div>'
                    % (e(w["name"]), state))
    body = "".join(rows) or '<div class="none">No worker heartbeats.</div>'
    waiting = snap["waiting_projects"]
    if waiting:
        body += '<div class="row"><span class="name muted">waiting: %s</span></div>' % e(", ".join(waiting))
    return '<div class="card workers"><h2>Workers</h2>%s</div>' % body


def _runs(runs, tz):
    e = html.escape
    rows = []
    for r in runs[:(CARD_H - CHROME) // ROW2_H]:
        if r["exit"] == 0:
            result = '<span class="ok">done</span>'
        else:
            why = r["limit"] or ("exit %s" % r["exit"] if r["exit"] is not None else "")
            result = '<span class="bad">failed%s</span>' % (" (%s)" % e(why) if why else "")
        detail = " · ".join(x for x in (e(r["model"] or ""), _duration(r["duration"]), result) if x)
        rows.append('<div class="row2"><div><span class="name"><b>%s</b></span><span class="right muted">%s</span>'
                    '</div><div class="sub">%s</div></div>'
                    % (e(r["project"] or "ad hoc"), _clock(r["finished"], tz), detail))
    body = "".join(rows) or '<div class="none">No runs in the last 24 hours.</div>'
    return '<div class="card runs"><h2>Last 24 hours</h2>%s</div>' % body


def _prs(prs, now):
    e = html.escape
    if prs is None or (prs.get("error") and prs.get("as_of") is None):
        return '<div class="card prs"><h2>Agent PRs to review</h2><div class="none">GitHub search ' \
               'unavailable.</div></div>'
    items, total = prs["items"], prs["total"]
    slots = (CARD_H - CHROME) // ROW2_H
    shown = items if total <= slots else items[:slots - 1]
    rows = []
    for pr in shown:
        repo = pr["repo"].split("/", 1)[-1]
        rows.append('<div class="row2"><div><span class="name"><b>%s</b> #%d%s</span>'
                    '<span class="right muted">%s</span></div><div class="sub">%s</div></div>'
                    % (e(repo), pr["number"], ' <span class="muted">· draft</span>' if pr["draft"] else "",
                       _age(now, pr["created"]), e(pr["title"])))
    if total > len(shown) and shown:
        rows.append('<div class="row2"><div class="muted">+%d more on GitHub</div></div>' % (total - len(shown)))
    body = "".join(rows) or '<div class="none">Nothing awaiting review.</div>'
    count = ' <span class="muted">· %d</span>' % total if total else ""
    return '<div class="card prs"><h2>Agent PRs to review%s</h2>%s</div>' % (count, body)


def _age(now, then):
    """How long ago, in the largest unit that reads well: "4 min", "3 h", "2 d"."""
    if then is None:
        return ""
    minutes = max(int((now - then).total_seconds() // 60), 0)
    if minutes < 60:
        return "%d min" % minutes
    if minutes < 48 * 60:
        return "%d h" % (minutes // 60)
    return "%d d" % (minutes // (24 * 60))


def _duration(seconds):
    if seconds is None:
        return ""
    if seconds < 90:
        return "%d s" % seconds
    if seconds < 90 * 60:
        return "%d min" % round(seconds / 60)
    return "%d h %d min" % (seconds // 3600, seconds % 3600 // 60)


def _clock(dt, tz):
    return dt.astimezone(tz).strftime("%-I:%M %p")
