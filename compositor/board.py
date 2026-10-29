"""The rubric board: viewport/rubric.html, what the compositor shows and why.

A page for people, not for the screen: one self-contained HTML file (inline
CSS, no scripts, a meta refresh) rendered from the same scan and decision as
``current.json``. It shows the pointer, the class ladder from ``rubric.PRIORITY``
with each live pane on its rung, the fallback chain (with the brief's age, so
a stale briefing fallback is visible before it is shown), every pane directory
on the bus with what ``rubric.explain`` made of it, and the rules in words.

``render`` returns the page and a key: a hash of everything but the
"generated" line, so the caller can skip rewrites that would change nothing.
"""

import hashlib
import html
from datetime import timedelta

from . import rubric, settings

STALE_BRIEF = timedelta(hours=36)
REFRESH_S = 10

CSS = """
:root { color-scheme: dark; }
html, body { margin: 0; padding: 0; background: #0e1612; color: #d8e4dc;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 40px; }
h1 { margin: 0; font-size: 28px; color: #e0a81c; }
h2 { margin: 32px 0 12px; font-size: 19px; color: #e8efe9; }
.sub, .muted { color: #8fa89a; }
.sub { margin: 4px 0 0; }
a { color: #9fd3b4; }
.card { background: #15211b; border: 1px solid #24372d; border-left: 6px solid #e0a81c;
  border-radius: 10px; padding: 14px 18px; }
.card.fallback { border-left-color: #8fa89a; }
.card .big { font-size: 22px; font-weight: 600; }
.card .meta { color: #a9bdb1; margin-top: 4px; }
ol.ladder { list-style: none; margin: 0; padding: 0; }
.rung { display: flex; gap: 14px; align-items: baseline; padding: 9px 12px;
  border-bottom: 1px solid #1f2e26; }
.rung.active { background: #1c2a22; border-left: 4px solid #e0a81c; }
.prio { flex: 0 0 44px; text-align: right; font-variant-numeric: tabular-nums; color: #8fa89a; }
.cls { flex: 0 0 120px; font-weight: 600; }
.rung .what { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.chip { display: inline-block; margin: 2px 6px 2px 0; padding: 1px 9px; border-radius: 999px;
  background: #22332a; font-size: 14px; }
.chip.showing { background: #e0a81c; color: #1b1405; font-weight: 600; }
.chip.rotating { background: #3a3317; color: #f0d28a; }
.warn { color: #f0a53a; font-weight: 600; }
.ovr { display: block; font-size: 12px; font-weight: 400; color: #e0a81c; }
tr.overridden td { color: #f0d28a; }
ul.history { margin: 0; padding-left: 20px; }
ul.history li { margin: 3px 0; }
ul.history .rejected { color: #f3b1a8; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 760px; font-size: 15px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #1f2e26; vertical-align: top; }
th { color: #8fa89a; font-weight: 500; }
td.id { font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size: 14px; }
.badge { display: inline-block; padding: 0 8px; border-radius: 6px; font-size: 13px;
  font-weight: 600; background: #22332a; white-space: nowrap; }
.badge.showing { background: #e0a81c; color: #1b1405; }
.badge.rotating { background: #3a3317; color: #f0d28a; }
.badge.expired, .badge.writing, .badge.off { background: #1f2e26; color: #8fa89a; }
.badge.malformed, .badge.invalid { background: #4a1f1f; color: #f3b1a8; }
ul.rules { margin: 0; padding-left: 20px; }
ul.rules li { margin: 4px 0; }
footer { margin-top: 36px; font-size: 14px; color: #8fa89a; }
@media (max-width: 520px) { .prio { flex-basis: 28px; } .cls { flex-basis: 84px; } }
"""


def render(pointer, rows, brief, now, url_base="http://pub.lan", tz=None, view=None):
    """Return ``(html, key)`` for the board.

    ``pointer`` is the decision, ``rows`` what ``rubric.explain`` returned for
    the same scan, ``brief`` a dict with ``present`` (bool) and ``mtime``
    (aware datetime or None) and ``title`` for the briefing slot, and ``now`` an aware
    datetime. Times are shown in ``tz`` (a tzinfo; None means the host's zone).
    ``view`` is the household settings the decision used: ``effective``,
    ``overrides``, ``history`` (from ``settings.load``) and ``brief_ok`` /
    ``brief_why`` (from ``settings.brief_usable``); None means the defaults.
    """
    e = html.escape
    url_base = url_base.rstrip("/")
    if view is None:
        eff = settings.effective({})
        ok, why = settings.brief_usable(brief, eff, now)
        view = {"effective": eff, "overrides": {}, "history": [], "brief_ok": ok, "brief_why": why}
    body = "\n".join([
        '<header><h1>brasenia viewport</h1>'
        '<p class="sub">What the compositor is showing, and why. '
        'This page refreshes every %d seconds. '
        '<a href="%s/viewport/configure.html">Change the settings</a></p></header>'
        % (REFRESH_S, e(url_base)),
        "<h2>Showing now</h2>",
        _now_card(pointer, brief, now, tz, view),
        "<h2>The rubric</h2>",
        '<p class="muted">The highest rung with a live pane wins. With nothing live, '
        'the fallbacks apply in order.</p>',
        _ladder(pointer, rows, brief, now, tz, view),
        "<h2>On the bus</h2>",
        _bus_table(rows, now, tz),
        "<h2>Settings</h2>",
        _settings(view, now, tz, url_base),
        "<h2>How it decides</h2>",
        _rules(view),
    ])
    key = hashlib.sha1(body.encode("utf-8")).hexdigest()
    page = """<!doctype html>
<!-- board:%(key)s -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="%(refresh)d">
<title>brasenia rubric</title>
<style>%(css)s</style>
</head>
<body>
<main>
%(body)s
<footer>Generated %(generated)s by the compositor on pub ·
<a href="%(base)s/viewport/current.json">current.json</a> ·
<a href="%(base)s/viewport/panes/">panes/</a></footer>
</main>
</body>
</html>
""" % {"key": key, "refresh": REFRESH_S, "css": CSS, "body": body, "base": e(url_base),
       "generated": e(_clock(now, now, tz, seconds=True))}
    return page, key


def key_of(page_text):
    """The key a rendered page carries, or None."""
    marker = "<!-- board:"
    start = page_text.find(marker)
    if start < 0:
        return None
    end = page_text.find(" -->", start)
    return page_text[start + len(marker):end] if end > 0 else None


def _now_card(pointer, brief, now, tz, view):
    e = html.escape
    if pointer.get("fallback") == "briefing":
        return ('<div class="card fallback"><div class="big">Fallback: the briefing (%s)</div>'
                '<div class="meta">Nothing on the bus is live. %s · <a href="%s">open it</a></div></div>'
                % (e(brief.get("title") or "briefing"), _brief_age(brief, now, tz), e(pointer["url"])))
    if pointer.get("fallback") == "status":
        return ('<div class="card fallback"><div class="big">Fallback: the status card</div>'
                '<div class="meta">Nothing on the bus is live, and the briefing fallback does not '
                'apply: %s. <a href="%s">open it</a></div></div>'
                % (e(view["brief_why"] or "no brief"), e(pointer["url"])))
    meta = ["%s (priority %s)" % (e(str(pointer.get("class"))), e(str(pointer.get("priority")))),
            "pane <code>%s</code>" % e(str(pointer.get("pane")))]
    try:
        expires = rubric.parse_time(pointer.get("expires_at"))
        meta.append("live until %s" % e(_clock(expires, now, tz)))
    except (ValueError, OverflowError):
        pass
    rotation = pointer.get("rotation")
    if rotation:
        meta.append("taking turns: %d of %d, %ss each"
                    % (rotation["index"] + 1, rotation["of"], rotation["dwell_s"]))
    return ('<div class="card"><div class="big">%s</div><div class="meta">%s · '
            '<a href="%s">open the pane</a></div></div>'
            % (e(str(pointer.get("title"))), " · ".join(meta), e(str(pointer.get("url")))))


def _ladder(pointer, rows, brief, now, tz, view):
    e = html.escape
    live = [r for r in rows if r["status"] in ("showing", "rotating", "outranked")]
    rungs = []
    prio_map = settings.priorities(view["effective"])
    for cls in sorted(settings.CLASSES, key=lambda c: (-prio_map[c], c)):
        prio = prio_map[cls]
        default = view["effective"].get("default.pane")
        chips = "".join('<span class="chip %s">%s%s</span>' % (
            r["status"], e(r["id"]), " · default" if r["id"] == default and cls == "ambient" else "")
            for r in live if r["class"] == cls)
        active = " active" if pointer.get("class") == cls and not pointer.get("fallback") else ""
        was = ('<span class="ovr">default %d</span>' % rubric.PRIORITY[cls]
               if "priority." + cls in view["overrides"] else "")
        rungs.append('<li class="rung%s"><span class="prio">%d</span><span class="cls">%s%s</span>'
                     '<span class="what">%s</span></li>'
                     % (active, prio, e(cls), was, chips or '<span class="muted">nothing live</span>'))
    active = " active" if pointer.get("fallback") == "briefing" else ""
    limit = view["effective"]["briefing.max_age_hours"]
    if not brief["present"]:
        what = '<span class="muted">skipped: no briefing is published in <code>viewport/briefing/</code></span>'
    elif not view["brief_ok"] and limit == 0:
        what = '<span class="warn">skipped: %s</span>' % html.escape(view["brief_why"])
    elif not view["brief_ok"]:
        published = _clock(brief["mtime"], now, tz) if brief["mtime"] else "at an unknown time"
        what = ('<span class="warn">skipped: the %s was published %s, %s</span>'
                % (html.escape(brief.get("title") or "briefing"), html.escape(published),
                   html.escape(view["brief_why"])))
    elif limit is not None:
        what = ("the %s in <code>viewport/briefing/</code>, published %s (within the %d h limit)"
                % (html.escape(brief.get("title") or "briefing"), html.escape(_clock(brief["mtime"], now, tz)), limit))
    else:
        what = "the %s in <code>viewport/briefing/</code>, %s" % (
            html.escape(brief.get("title") or "briefing"), _brief_age(brief, now, tz))
    rungs.append('<li class="rung%s"><span class="prio">%d</span><span class="cls">briefing</span>'
                 '<span class="what">fallback 1: %s</span></li>'
                 % (active, rubric.PRIORITY["briefing"], what))
    active = " active" if pointer.get("fallback") == "status" else ""
    rungs.append('<li class="rung%s"><span class="prio">&ndash;</span><span class="cls">status card</span>'
                 '<span class="what">fallback 2: <code>viewport/status.html</code>, written when '
                 'it is needed</span></li>' % active)
    return '<ol class="ladder">\n%s\n</ol>' % "\n".join(rungs)


def _bus_table(rows, now, tz):
    e = html.escape
    if not rows:
        return '<p class="muted">The bus is empty: no pane directories under <code>viewport/panes/</code>.</p>'
    out = ['<div class="scroll"><table><thead><tr><th>pane</th><th>title</th><th>class</th>'
           '<th>origin</th><th>live until</th><th>status</th><th>why</th></tr></thead><tbody>']
    for r in rows:
        until = _clock(r["expires"], now, tz) if "expires" in r else ""
        cls = "%s (%d)" % (r["class"], r["priority"]) if "class" in r else ""
        out.append('<tr><td class="id">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                   '<td><span class="badge %s">%s</span></td><td>%s</td></tr>'
                   % (e(r["id"]), e(r.get("title", "")), e(cls), e(r.get("origin", "")),
                      e(until), r["status"], e(r["status"]), e(r.get("reason") or "")))
    out.append("</tbody></table></div>")
    return "\n".join(out)


def _rules(view):
    dwell = view["effective"]["rotation.dwell_s"]
    limit = view["effective"]["briefing.max_age_hours"]
    link_rule = ("Link panes are on." if view.get("link_panes") else
                 "Link panes are off until the renderer can show web pages safely.")
    if limit is None:
        brief_rule = "the briefing in <code>viewport/briefing/</code> is shown if it exists, however old it is"
    elif limit == 0:
        brief_rule = "the briefing fallback is off, so the status card is shown"
    else:
        brief_rule = ("the briefing in <code>viewport/briefing/</code> is shown if it was published "
                      "within the last %d hours" % limit)
    return """<ul class="rules">
<li>A pane is live from its manifest's <code>created</code> time for <code>ttl_minutes</code>; its producer keeps it live by rewriting the manifest.</li>
<li>The live pane on the highest rung wins. On a tie, <code>operator</code> panes go before <code>fleet</code> ones, then the newest.</li>
<li>Panes that tie on rung and origin with the winner take turns, each for its <code>dwell_s</code> (%d s unless the manifest says otherwise).</li>
<li>With nothing live, %s; otherwise the status card.</li>
<li>A pane directory without both <code>pane.html</code> and <code>manifest.json</code> is still being written, and a bad manifest is skipped; neither can blank the screen.</li>
<li>A pane whose manifest has a <code>source</code> is a link pane: the screen shows that web page and needs no <code>pane.html</code>. %s</li>
</ul>""" % (dwell, brief_rule, link_rule)


def _brief_age(brief, now, tz):
    if not brief.get("mtime"):
        return "published at an unknown time"
    age = now - brief["mtime"]
    text = "published %s" % _clock(brief["mtime"], now, tz)
    if age > STALE_BRIEF:
        return '<span class="warn">%s: stale</span>' % html.escape(text)
    return html.escape(text)


def _clock(when, now, tz, seconds=False):
    """A time in ``tz`` people read at a glance: today as a time, otherwise
    with the date. ``seconds`` (the footer) adds seconds and the zone name."""
    local, today = when.astimezone(tz), now.astimezone(tz)
    fmt = "%-I:%M:%S %p %Z" if seconds else "%-I:%M %p"
    if local.date() != today.date():
        fmt = "%a %b %-d, " + fmt
    text = local.strftime(fmt)
    if not seconds:
        delta = when - now
        text += " (in %s)" % _span(delta) if delta.total_seconds() > 0 else " (%s ago)" % _span(-delta)
    return text


def _span(delta):
    s = int(delta.total_seconds())
    if s < 90:
        return "%d s" % s
    if s < 90 * 60:
        return "%d min" % round(s / 60)
    if s < 36 * 3600:
        return "%d h" % round(s / 3600)
    return "%d days" % round(s / 86400)


def _settings(view, now, tz, url_base):
    e = html.escape
    eff, overrides = view["effective"], view["overrides"]
    defaults = settings.defaults()
    def show(key, v):
        if v is None:
            return "none (they take turns)" if key == "default.pane" else "no limit"
        return str(v)
    rows = []
    for key, (_, _, label, _) in settings.SPEC.items():
        rows.append('<tr class="%s"><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % ("overridden" if key in overrides else "", e(label), e(show(key, eff[key])),
                       e(show(key, defaults[key]))))
    fixed = [k for k in overrides if k in settings.SPEC]   # standing slots are not overrides
    slots = len(settings.links(eff))
    out = ['<p class="muted">%s%s <a href="%s/viewport/configure.html">Change them</a>.</p>'
           % ("%d override%s in force." % (len(fixed), "" if len(fixed) == 1 else "s")
              if fixed else "Every setting is at its default.",
              " %d standing slot%s." % (slots, "" if slots == 1 else "s") if slots else "",
              e(url_base)),
           '<div class="scroll"><table><thead><tr><th>setting</th><th>now</th><th>default</th>'
           '</tr></thead><tbody>%s</tbody></table></div>' % "".join(rows)]
    if view["history"]:
        items = []
        for h in view["history"]:
            try:
                when = _clock(rubric.parse_time(h["ts"]), now, tz)
            except (ValueError, OverflowError, TypeError):
                when = str(h["ts"])
            label = settings.SPEC[h["key"]][2] if h["key"] in settings.SPEC else str(h["key"])
            if settings.is_link(h["key"]):
                label = "Standing slot %s" % h["key"][len(settings.LINK_PREFIX):]
            if h["error"]:
                what = '<span class="rejected">rejected %s %s: %s</span>' % (
                    e(str(h["action"])), e(label), e(h["error"]))
            elif h["action"] == "undo":
                what = ("%s removed" if settings.is_link(h["key"]) else "%s back to its default") % e(label)
            elif settings.is_link(h["key"]):
                what = "%s set to %s (%s)" % (e(label), e(h["value"]["title"]), e(h["value"]["source"]["url"]))
            else:
                what = "%s set to %s" % (e(label), e(str(h["value"])))
            items.append("<li>%s · %s%s</li>" % (e(when), what,
                         " · from %s" % e(str(h["client"])) if h["client"] else ""))
        out.append("<h3>Recent changes</h3>")
        out.append('<ul class="history">%s</ul>' % "".join(items))
    return "\n".join(out)
