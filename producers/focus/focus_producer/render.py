"""Render the focus pane: one 1280×720 band, inline CSS, no scripts or assets.

Layout is fixed-height so the band never overflows: a 150 px header
(52 + 3×32), a 36 px table head, MAX_ROWS 44 px rows and a 40 px "+N more"
line add up to the 622 px main area, which starts at the 24 px top margin
and ends at y=646, above the 50 px clock strip and its 24 px margin.
The "as of" footer sits bottom-left and ends well short of the
bottom-right 220×50 px clock corner.
"""

import html
import re
from datetime import timezone

from .github import parse_ts

WIDTH, HEIGHT = 1280, 720
MAX_ROWS = 9
TITLE_CHARS = 70

BG, TEXT, MUTED, ACCENT = "#0e2b1a", "#f3f0e8", "#cdd6d0", "#E0A81C"

# The stamp sits between markers so a failed refresh can rewrite just this
# span of the previous pane.html and leave its data alone.
STAMP_OPEN, STAMP_CLOSE = "<!--asof-->", "<!--/asof-->"
_STAMP_RE = re.compile(re.escape(STAMP_OPEN) + ".*?" + re.escape(STAMP_CLOSE), re.S)

CSS = """
html, body { margin: 0; padding: 0; }
body { width: 1280px; height: 720px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif;
  font-size: 20px; line-height: 1.3; }
.main { position: absolute; top: 24px; left: 24px; right: 24px; height: 622px;
  overflow: hidden; }
header { height: 150px; }
h1 { margin: 0; font-size: 40px; line-height: 52px; color: %(accent)s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.line { font-size: 22px; line-height: 32px; color: %(muted)s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.line b { color: %(text)s; font-weight: normal; }
table { width: 100%%; table-layout: fixed; border-collapse: collapse; }
th { height: 36px; text-align: left; font-weight: normal; font-size: 20px;
  color: %(muted)s; border-bottom: 1px solid %(muted)s; }
td { height: 44px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.num { width: 80px; } .who { width: 170px; } .age { width: 80px; }
.chk { width: 140px; } .rev { width: 210px; }
.draft { color: %(muted)s; }
.bad { color: %(accent)s; }
.more, .empty { height: 40px; line-height: 40px; color: %(muted)s; }
.foot { position: absolute; left: 24px; bottom: 24px; width: 1000px; height: 26px;
  font-size: 20px; line-height: 26px; color: %(muted)s;
  white-space: nowrap; overflow: hidden; }
""" % {"bg": BG, "text": TEXT, "muted": MUTED, "accent": ACCENT}


def render(repo, data, pipeline_row, as_of, now):
    """Return pane.html for ``repo``.

    ``data`` is GitHub.repo()'s dict, ``pipeline_row`` the repo's
    pipeline.json object or None, ``as_of`` when the data was fetched and
    ``now`` the render time (both aware datetimes).
    """
    e = html.escape
    name = repo.split("/", 1)[1]
    lines = ['<div class="line">main: %s</div>' % _main_line(data.get("main"), now)]
    if pipeline_row:
        lines.append('<div class="line">pipeline: %s</div>' % _pipeline_line(pipeline_row))

    pulls = data.get("pulls") or []
    count = "%d open pull request%s" % (len(pulls), "" if len(pulls) == 1 else "s")
    lines.insert(0, '<div class="line"><b>%s</b> · %s</div>' % (e(repo), count))

    rows = []
    for pr in pulls[:MAX_ROWS]:
        title = pr["title"]
        if len(title) > TITLE_CHARS:
            title = title[:TITLE_CHARS - 1] + "…"
        draft = '<span class="draft">[draft] </span>' if pr.get("draft") else ""
        rows.append(
            "<tr><td>#%d</td><td>%s%s</td><td>%s</td><td>%s</td>%s%s</tr>" % (
                pr["number"], draft, e(title), e(pr["author"]),
                _age(parse_ts(pr["created_at"]), now),
                _cell(pr["checks"], pr["checks"] == "failing"),
                _cell(pr["review"], pr["review"] == "changes requested"),
            ))
    extra = ""
    if not pulls:
        extra = '<div class="empty">No open pull requests.</div>'
    elif len(pulls) > MAX_ROWS:
        extra = '<div class="more">+%d more</div>' % (len(pulls) - MAX_ROWS)

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>%(title)s</title>
<style>%(css)s</style></head>
<body>
<div class="main">
<header>
<h1>%(name)s</h1>
%(lines)s
</header>
<table>
<colgroup><col class="num"><col><col class="who"><col class="age"><col class="chk"><col class="rev"></colgroup>
<thead><tr><th>PR</th><th>title</th><th>author</th><th>age</th><th>checks</th><th>review</th></tr></thead>
<tbody>
%(rows)s
</tbody>
</table>
%(extra)s
</div>
<div class="foot">%(stamp)s</div>
</body></html>
""" % {
        "title": e(pane_title(repo)),
        "css": CSS,
        "name": e(name),
        "lines": "\n".join(lines),
        "rows": "\n".join(rows),
        "extra": extra,
        "stamp": stamp(as_of),
    }


def restamp(page, failed_at):
    """Rewrite only the "as of" stamp of an existing pane.html after a failed refresh.

    The data and its original "data as of" time stay; the stamp gains when
    the refresh was last attempted, so a stale pane reads as stale on the wall.
    Returns None when the page has no stamp to rewrite.
    """
    found = _STAMP_RE.search(page)
    if not found:
        return None
    old = found.group(0)[len(STAMP_OPEN):-len(STAMP_CLOSE)]
    kept = old.split(" · ", 1)[0]
    note = "%s · GitHub unavailable, last tried %s" % (kept, _hhmm(failed_at))
    return page[:found.start()] + STAMP_OPEN + note + STAMP_CLOSE + page[found.end():]


def stamp(as_of):
    return STAMP_OPEN + "data as of %s" % _hhmm(as_of) + STAMP_CLOSE


def pane_title(repo):
    return "%s — open pull requests" % repo.split("/", 1)[1]


def _main_line(main, now):
    if not main:
        return "<b>no completed runs</b>"
    conclusion = main["conclusion"]
    cls = ' class="bad"' if conclusion not in ("success", "skipped", "neutral") else ""
    when = ""
    if main.get("updated_at"):
        when = ", %s ago" % _age(parse_ts(main["updated_at"]), now)
    name = (" · %s" % html.escape(main["name"])) if main.get("name") else ""
    return "<b%s>%s</b>%s%s" % (cls, html.escape(conclusion), name, when)


def _pipeline_line(row):
    parts = ["<b>%s</b>" % html.escape(str(row.get("stage", "?")))]
    if row.get("sha"):
        parts.append(html.escape(str(row["sha"])[:7]))
    since = row.get("since")
    if since:
        try:
            parts.append("since %s" % _hhmm(parse_ts(str(since))))
        except ValueError:
            pass
    return " · ".join(parts)


def _cell(text, bad):
    return '<td%s>%s</td>' % (' class="bad"' if bad else "", html.escape(text))


def _age(then, now):
    secs = max(0, int((now - then).total_seconds()))
    if secs < 3600:
        return "%dm" % (secs // 60)
    if secs < 86400:
        return "%dh" % (secs // 3600)
    return "%dd" % (secs // 86400)


def _hhmm(ts):
    """Local wall-clock HH:MM, the time a person in the room reads."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone().strftime("%H:%M")


