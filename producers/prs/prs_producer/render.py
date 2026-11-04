"""Render the PRs pane: one 1920×1080 band, inline CSS, no scripts.

Geometry (inside the 36 px margins): a 90 px header, a 144 px row of three
counts and a 663 px card holding the running list, with 18 px gaps, fill the
933 px main area that ends at y=969, above the bottom-right 330×75 px clock
corner. The footer sits bottom-left and stops 534 px short of the right edge.

The list is ten 57 px rows, newest event first. Each row is a status chip
(open, draft, merged, closed), the repo, the number, the title, who opened it
and when the event was. The colours follow GitHub's own: green open,
grey draft, purple merged, red closed.

With pub's GitHub token, an open row whose state is known shows what it waits
on in place of its author (#137): "checks failing", "armed", "awaiting
review", "checks running" or "reviewed", in that order of precedence. Without
the token the rows show authors and the footer says "no GitHub token"
(ADR-0021).
"""

import html

BG, CARD, LINE = "#0f1518", "#172025", "#2a373e"
TEXT, MUTED, FAINT = "#e4ebee", "#9fb0b8", "#73858e"
BAND, BAND_TEXT = "#1d3a33", "#cdeee3"
OPEN, DRAFT, MERGED, CLOSED, AMBER = "#3fb950", "#8b949e", "#a371f7", "#f85149", "#f0a53a"
RUNNING = "#58a6ff"
ROWS = 10

STATUS = {
    "open": ("open", OPEN),
    "draft": ("draft", DRAFT),
    "merged": ("merged", MERGED),
    "closed": ("closed", CLOSED),
}

CSS = """
html, body { margin: 0; padding: 0; }
body { width: 1920px; height: 1080px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 31.5px; line-height: 39px; }
.main { position: absolute; top: 36px; left: 36px; right: 36px; height: 933px; overflow: hidden; }
header { height: 90px; display: flex; align-items: center; gap: 30px; border-radius: 15px;
  padding: 0 27px; box-sizing: border-box; background: %(band)s; }
h1 { margin: 0; font-size: 51px; line-height: 60px; color: #ffffff; white-space: nowrap; }
h1 span { font-size: 33px; font-weight: normal; color: %(band_text)s; }
.summary { margin-left: auto; font-size: 30px; color: %(amber)s; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; min-width: 0; }
.tiles { display: flex; gap: 18px; margin-top: 18px; height: 144px; }
.tile { flex: 1 1 0; min-width: 0; background: %(card)s; border-radius: 15px; padding: 12px 24px;
  box-sizing: border-box; }
.tile .n { height: 72px; font-size: 60px; line-height: 72px; font-weight: bold; }
.tile .l { height: 39px; font-size: 30px; color: %(muted)s; white-space: nowrap; }
.card { margin-top: 18px; height: 663px; background: %(card)s; border-radius: 15px; padding: 15px 24px;
  box-sizing: border-box; overflow: hidden; }
h2 { margin: 0; height: 48px; font-size: 31.5px; line-height: 48px; color: %(muted)s;
  font-weight: normal; white-space: nowrap; }
.row { height: 57px; box-sizing: border-box; display: flex; align-items: center; gap: 18px;
  border-bottom: 1.5px solid %(line)s; white-space: nowrap; }
.chip { flex: 0 0 156px; box-sizing: border-box; height: 45px; line-height: 39px; border: 3px solid;
  border-radius: 9px; text-align: center; font-size: 30px; font-weight: bold; }
.repo { flex: 0 0 360px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; }
.num { flex: 0 0 105px; color: %(muted)s; }
.title { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.who { flex: 0 0 245px; color: %(muted)s; overflow: hidden; text-overflow: ellipsis; }
.who.state { font-size: 30px; }
.when { flex: 0 0 168px; color: %(muted)s; text-align: right; }
.n.open { color: %(open)s; }
.n.merged { color: %(merged)s; }
.none { color: %(faint)s; font-style: italic; padding-top: 9px; }
.foot { position: absolute; left: 36px; bottom: 36px; width: 1350px; height: 39px; font-size: 30px;
  line-height: 39px; color: %(faint)s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
""" % {"bg": BG, "text": TEXT, "card": CARD, "line": LINE, "muted": MUTED, "faint": FAINT,
       "band": BAND, "band_text": BAND_TEXT, "amber": AMBER, "open": OPEN, "merged": MERGED}


def render(data, status, scope, now, tz):
    """pane.html.

    ``data`` is a ``Client.snapshot`` result; ``status`` is ``{"as_of",
    "error", "tried", "token", "paused", "states"}``: when ``data`` was
    fetched, the last refresh's failure (or None), when that refresh ran,
    whether the producer holds a token GitHub accepts, whether the state
    query is paused for GitHub's budget, and the open rows' known states by
    node id.
    """
    e = html.escape
    tiles = "".join('<div class="tile"><div class="n%s">%d</div><div class="l">%s</div></div>'
                    % (cls, n, e(label)) for n, label, cls in (
                        (data["open"], "open now", " open"),
                        (data["opened_today"], "opened today", ""),
                        (data["merged_today"], "merged today", " merged")))
    states = status.get("states") or {}
    rows = "".join(_row(ev, states.get(ev.get("id")), now, tz) for ev in data["events"][:ROWS])
    rows = rows or '<div class="none">No pull requests yet.</div>'
    foot = "GitHub search · as of %s" % _clock(status["as_of"], tz)
    if not status.get("token"):
        foot += " · no GitHub token"
    elif status.get("paused"):
        foot += " · PR state paused, rate limit low"
    summary = ("GitHub unavailable, last tried %s" % _clock(status["tried"], tz)
               if status["error"] else "")
    where = scope[len("org:"):] if scope.startswith("org:") else scope
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="brasenia-canvas" content="1920x1080">
<title>Pull requests</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>Pull requests <span>%(where)s</span></h1><div class="summary">%(summary)s</div></header>
<div class="tiles">%(tiles)s</div>
<div class="card"><h2>Latest, newest first</h2>%(rows)s</div>
</div>
<div class="foot">%(foot)s</div>
</body></html>
""" % {"css": CSS, "where": e(where), "summary": e(summary), "tiles": tiles, "rows": rows,
       "foot": e(foot)}


def waits_on(state):
    """What an open PR waits on, as ``(word, colour)``: failing checks first,
    then auto-merge armed, then the review gate (.github ADR-0013), then
    running checks. A reviewed PR with nothing else pending reads "reviewed":
    the next step is a person's, to triage the findings and arm it."""
    if state["checks"] == "failing":
        return "checks failing", CLOSED
    if state["armed"]:
        return "armed", OPEN
    if not state["reviewed"]:
        return "awaiting review", AMBER
    if state["checks"] == "pending":
        return "checks running", RUNNING
    return "reviewed", TEXT


def _row(ev, state, now, tz):
    e = html.escape
    label, colour = STATUS[ev["status"]]
    if ev["status"] == "open" and state:
        word, tint = waits_on(state)
        who = '<span class="who state" style="color: %s">%s</span>' % (tint, word)
    else:
        who = '<span class="who">%s</span>' % e(ev["who"])
    return ('<div class="row"><span class="chip" style="color: %s; border-color: %s">%s</span>'
            '<span class="repo">%s</span><span class="num">#%d</span><span class="title">%s</span>'
            '%s<span class="when">%s</span></div>'
            % (colour, colour, label, e(ev["repo"].split("/", 1)[-1]), ev["number"], e(ev["title"]),
               who, _when(now, ev["when"], tz)))


def _when(now, then, tz):
    """When the event was: "now" or "4 min" within the hour, then "6:12 PM" today,
    "Sat" within the week and "Oct 30" before that, in the household's zone."""
    minutes = max(int((now - then).total_seconds() // 60), 0)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return "%d min" % minutes
    local, today = then.astimezone(tz), now.astimezone(tz).date()
    if local.date() == today:
        return _clock(then, tz)
    if (today - local.date()).days < 7:
        return local.strftime("%a")
    return local.strftime("%b %-d")


def _clock(dt, tz):
    return dt.astimezone(tz).strftime("%-I:%M %p")
