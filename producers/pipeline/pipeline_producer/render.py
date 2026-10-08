"""Render the change-pipeline pane: one 1280×720 band, inline CSS and SVG, no scripts.

Layout is fixed-height so the band never overflows: a 64 px header and
MAX_STRIPS strips of 130 px plus an 8 px gap add up to 616 px of the 622 px
main area, which starts at the 24 px top margin and ends at y=646, above the
50 px clock strip and its 24 px margin. The "as of" footer sits bottom-left
and ends well short of the bottom-right 220×50 px clock corner.

Each strip is six state-coloured boxes joined by five inline-SVG edges. The
edge into the change's frontier (the first stage after the furthest green
one) is drawn as a dashed line whose dashes travel left to right, a
``stroke-dashoffset`` keyframe animation, so the wall shows where the change
is moving without any script.
"""

import html
import re
from datetime import timezone

from .document import parse_ts, stages

MAX_STRIPS = 4

BG, TEXT, MUTED, EDGE = "#111217", "#f3f0e8", "#b8bcc6", "#4b5563"
# The Change — Pipeline dashboard's state palette (drosera dashboards/change-pipeline.json).
STATE_COLOURS = {3: "#73BF69", 2: "#F2495C", 1: "#5794F2", 0: "#6b7280"}
RED = STATE_COLOURS[2]
LABELS = {
    "pushed": "pushed", "pr_open": "PR open", "checks_green": "checks",
    "merged": "merged", "applied": "applied", "live": "live",
}

# The stamp sits between markers so a cycle without fresh data can rewrite
# just this span of the previous pane.html and leave its strips alone.
STAMP_OPEN, STAMP_CLOSE = "<!--asof-->", "<!--/asof-->"
_STAMP_RE = re.compile(re.escape(STAMP_OPEN) + ".*?" + re.escape(STAMP_CLOSE), re.S)

CSS = """
html, body { margin: 0; padding: 0; }
body { width: 1280px; height: 720px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 20px; line-height: 1.2; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px;
  overflow: hidden; }
header { height: 64px; display: flex; justify-content: space-between;
  align-items: baseline; }
h1 { margin: 0; font-size: 40px; line-height: 52px; font-weight: bold; }
.more { font-size: 28px; color: %(muted)s; }
.strip { box-sizing: border-box; height: 130px; margin-bottom: 8px;
  padding: 4px 8px; border: 3px solid transparent; border-radius: 8px; }
.strip.stuck { border-color: %(red)s; }
.head { height: 30px; line-height: 30px; font-size: 22px; color: %(muted)s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.head b { color: %(text)s; }
.head .bad { color: %(red)s; font-weight: bold; }
.row { display: flex; align-items: center; height: 82px; margin-top: 4px; }
.box { box-sizing: border-box; flex: 0 0 170px; width: 170px; height: 80px;
  padding: 4px 8px; border-radius: 6px; color: #0b0f14; overflow: hidden; }
.box div { height: 24px; line-height: 24px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.box .stage { font-weight: bold; }
.box .sha { font-family: "DejaVu Sans Mono", monospace; }
.s3 { background: %(s3)s; } .s2 { background: %(s2)s; } .s1 { background: %(s1)s; }
.s0 { background: %(s0)s; color: %(text)s; }
svg.edge { flex: 0 0 36px; width: 36px; height: 82px; }
svg.edge line { stroke: %(edge)s; stroke-width: 4; }
svg.edge polygon { fill: %(edge)s; }
svg.edge.go line { stroke: %(text)s; stroke-width: 6; stroke-dasharray: 6 4;
  animation: travel 0.8s linear infinite; }
svg.edge.go polygon { fill: %(text)s; }
@keyframes travel { from { stroke-dashoffset: 10; } to { stroke-dashoffset: 0; } }
.foot { position: absolute; left: 24px; bottom: 24px; width: 900px; height: 26px;
  font-size: 20px; line-height: 26px; color: %(muted)s;
  white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "text": TEXT, "muted": MUTED, "edge": EDGE, "red": RED,
       "s3": STATE_COLOURS[3], "s2": STATE_COLOURS[2], "s1": STATE_COLOURS[1],
       "s0": STATE_COLOURS[0]}

EDGE_SVG = ('<svg class="edge%s" viewBox="0 0 36 82" aria-hidden="true">'
            '<line x1="2" y1="41" x2="26" y2="41"/>'
            '<polygon points="26,33 35,41 26,49"/></svg>')


def render(flying, as_of, now):
    """Return pane.html for ``flying``, the in-flight repos oldest first.

    ``as_of`` is the document's ``generated_at`` and ``now`` the render
    time (both aware datetimes). Only the first MAX_STRIPS repos get a strip.
    """
    shown = flying[:MAX_STRIPS]
    extra = len(flying) - len(shown)
    more = '<span class="more">+%d more</span>' % extra if extra > 0 else ""
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>%(title)s</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header><h1>%(title)s</h1>%(more)s</header>
%(strips)s
</div>
<div class="foot">%(stamp)s</div>
</body></html>
""" % {
        "title": html.escape(pane_title(len(flying))),
        "css": CSS,
        "more": more,
        "strips": "\n".join(_strip(repo, now) for repo in shown),
        "stamp": stamp(as_of),
    }


def pane_title(count):
    return "%d change%s in flight" % (count, "" if count == 1 else "s")


def frontier(states):
    """Index of the stage the change is travelling into, or None.

    That is the first stage after the furthest green one. In flight, the
    furthest stage that is not green is nearly always ``live``; the frontier
    is where the change actually is (a failed ``applied`` stops it there).
    """
    green = [i for i, s in enumerate(states) if s == 3]
    if not green:
        return None
    nxt = green[-1] + 1
    return nxt if nxt < len(states) else None


def restamp(page, tried_at):
    """Rewrite only the "as of" stamp of an existing pane.html after a cycle without fresh data.

    The strips and their original "data as of" time stay; the stamp gains
    when fresh data was last looked for, so a stale pane reads as stale on
    the wall. Returns None when the page has no stamp to rewrite.
    """
    found = _STAMP_RE.search(page)
    if not found:
        return None
    old = found.group(0)[len(STAMP_OPEN):-len(STAMP_CLOSE)]
    kept = old.split(" · ", 1)[0]
    note = "%s · no fresh pipeline data, last tried %s" % (kept, _hhmm(tried_at))
    return page[:found.start()] + STAMP_OPEN + note + STAMP_CLOSE + page[found.end():]


def stamp(as_of):
    return STAMP_OPEN + "data as of %s" % _hhmm(as_of) + STAMP_CLOSE


def _strip(repo, now):
    e = html.escape
    entries = stages(repo)
    states = [_state(entry.get("state")) for entry in entries]
    go = frontier(states)

    cells = []
    for i, (entry, state) in enumerate(zip(entries, states)):
        if i:
            cells.append(EDGE_SVG % (" go" if i == go else ""))
        sha = entry.get("sha")
        detail = entry.get("detail")
        cells.append(
            '<div class="box s%d"><div class="stage">%s</div>'
            '<div class="sha">%s</div><div>%s</div></div>' % (
                state, e(LABELS[entry["stage"]]),
                e(str(sha)[:7]) if sha else "—",
                e(str(detail)) if detail else "&nbsp;"))

    name = str(repo.get("repo", "?"))
    parts = ["<b>%s</b>" % e(name.split("/", 1)[-1])]
    head = repo.get("head")
    if isinstance(head, dict) and head.get("sha"):
        parts.append("head %s" % e(str(head["sha"])[:7]))
    minutes = _minutes_since(repo.get("in_flight_since"), now)
    if minutes is not None:
        parts.append("in flight %d min" % minutes)
    stuck = repo.get("stuck") is True
    if stuck:
        parts.append('<span class="bad">stuck%s</span>'
                     % ("" if minutes is None else " %d min" % minutes))

    return ('<div class="strip%s">\n<div class="head">%s</div>\n'
            '<div class="row">%s</div>\n</div>' % (
                " stuck" if stuck else "", " · ".join(parts), "".join(cells)))


def _state(value):
    """The stage's state code, 0 for anything that is not one of 0..3.

    A list or object in the document is a producer bug upstream, not a reason
    to crash this cycle, so it renders grey like a missing stage.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value in STATE_COLOURS else 0


def _minutes_since(value, now):
    try:
        then = parse_ts(value)
    except (TypeError, ValueError, AttributeError):
        return None
    return max(0, int((now - then).total_seconds()) // 60)


def _hhmm(ts):
    """Local wall-clock HH:MM, the time a person in the room reads."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone().strftime("%H:%M")
