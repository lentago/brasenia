"""The rubric configurator: viewport/configure.html, beside the rubric board.

A page for people (not a pane), so it may carry a small inline script. It
shows every setting in ``settings.SPEC`` prefilled with its effective value,
and on Save posts one pub-signals signal per change to ``/api/signals/rubric``:
``set`` with the new value in ``label``, or ``undo`` when a field is cleared
or put back to its default. The compositor reads the log back, validates it
and applies it (ADR-0011); this page never decides anything itself.

Below them it lists the standing slots (``link.<pane-id>`` settings, #97,
ADR-0018) with a Remove button each (``undo``), and a form that adds one
(``set``, with the slot as a JSON object in ``label``).
"""

import hashlib
import html
import json

from . import settings

ENDPOINT = "/api/signals/rubric"

CSS = """
:root { color-scheme: dark; }
html, body { margin: 0; padding: 0; background: #0e1612; color: #d8e4dc;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 24px 16px 40px; }
h1 { margin: 0; font-size: 28px; color: #e0a81c; }
h2 { margin: 28px 0 10px; font-size: 19px; color: #e8efe9; }
.sub, .muted, .help { color: #8fa89a; }
a { color: #9fd3b4; }
.field { display: grid; grid-template-columns: 1fr 260px; gap: 4px 16px;
  padding: 12px 0; border-bottom: 1px solid #1f2e26; align-items: center; }
.field label { font-weight: 600; }
.field .help { grid-column: 1 / -1; font-size: 14px; }
.field .default { font-size: 14px; color: #8fa89a; }
.field.overridden label::after { content: " · overridden"; color: #e0a81c; font-weight: 500; }
input, select { width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 6px;
  border: 1px solid #2c4436; background: #15211b; color: #e8efe9; font: inherit; }
.buttons { margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap; }
button { padding: 8px 16px; border-radius: 8px; border: 0; font: inherit; font-weight: 600;
  cursor: pointer; background: #e0a81c; color: #1b1405; }
button.secondary { background: #22332a; color: #d8e4dc; }
table.slots { width: 100%; border-collapse: collapse; margin: 8px 0 4px; }
table.slots td, table.slots th { text-align: left; padding: 6px 8px 6px 0; border-bottom: 1px solid #1f2e26;
  vertical-align: top; overflow-wrap: anywhere; }
table.slots button { padding: 4px 10px; }
.slot-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; margin-top: 12px; }
.slot-fields label { display: block; font-weight: 600; margin-bottom: 4px; }
.slot-fields .wide { grid-column: 1 / -1; }
#status { margin-top: 16px; white-space: pre-line; }
@media (max-width: 520px) { .field { grid-template-columns: 1fr 100px; } }
"""

SCRIPT = """
const ENDPOINT = %(endpoint)s;
const CURRENT = %(current)s, DEFAULTS = %(defaults)s, OVERRIDDEN = %(overridden)s;
const status = document.getElementById("status");

function str(v) { return v === null || v === undefined ? "" : String(v); }

async function send(id, action, label) {
  const body = {id: id, action: action};
  if (label !== undefined) body.label = label;
  const r = await fetch(ENDPOINT, {method: "POST", headers: {"Content-Type": "application/json"},
                                   body: JSON.stringify(body)});
  if (!r.ok) throw new Error(id + ": " + r.status + " " + (await r.text()));
}

async function apply(changes, out) {
  out = out || status;
  if (!changes.length) { out.textContent = "Nothing changed."; return; }
  out.textContent = "Saving " + changes.length + " change(s)…";
  try {
    for (const c of changes) await send(c.id, c.action, c.label);
    out.textContent = "Saved. The compositor applies changes within a few seconds; " +
                      "this page reloads to show what it applied.";
    setTimeout(() => location.reload(), 7000);
  } catch (e) {
    out.textContent = "Could not save: " + e.message;
  }
}

document.getElementById("form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const changes = [];
  for (const id of Object.keys(CURRENT)) {
    const v = document.getElementById(id).value.trim();
    const backToDefault = v === "" || v === str(DEFAULTS[id]);
    if (backToDefault) {
      if (OVERRIDDEN.includes(id)) changes.push({id: id, action: "undo"});
    } else if (v !== str(CURRENT[id])) {
      changes.push({id: id, action: "set", label: v});
    }
  }
  apply(changes);
});

document.getElementById("reset").addEventListener("click", () => {
  apply(OVERRIDDEN.map((id) => ({id: id, action: "undo"})));
});

const slotStatus = document.getElementById("slot-status");
for (const b of document.querySelectorAll("button.remove")) {
  b.addEventListener("click", () => apply([{id: b.dataset.id, action: "undo"}], slotStatus));
}
document.getElementById("slot-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const v = (name) => document.getElementById("slot-" + name).value.trim();
  const id = v("id");
  if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(id)) {
    slotStatus.textContent = "The pane id is lower-case letters, digits and dashes, starting with a letter or digit.";
    return;
  }
  const label = JSON.stringify({title: v("title"), url: v("url"), theme: v("theme")});
  if (label.length > %(max_label)d) {
    slotStatus.textContent = "Too long to save: shorten the title or the URL.";
    return;
  }
  apply([{id: "link." + id, action: "set", label: label}], slotStatus);
});
"""


MAX_LABEL = 500   # pub-signals' limit on a label


def render(eff, overrides, url_base="http://pub.lan", resting=(), link_panes=False):
    """Return ``(html, key)``; the key changes only when the page's content does.

    ``resting`` lists the live ambient panes as ``(id, title)``, the choices
    for the default resting pane. ``link_panes`` says whether the compositor
    shows link panes, for the standing slots' note."""
    e = html.escape
    base = url_base.rstrip("/")
    defaults = settings.defaults()
    fields = []
    for key, (lo, hi, label, help_text) in settings.SPEC.items():
        default = defaults[key]
        if key == "default.pane":
            fields.append(_pane_field(key, label, help_text, eff[key], key in overrides, resting))
            continue
        fields.append(
            '<div class="field%s"><label for="%s">%s</label>'
            '<input id="%s" name="%s" type="number" min="%d" max="%d" step="1" value="%s" placeholder="%s">'
            '<div class="help">%s <span class="default">Default: %s.</span></div></div>'
            % (" overridden" if key in overrides else "", e(key), e(label), e(key), e(key), lo, hi,
               e("" if eff[key] is None else str(eff[key])),
               e("no limit" if default is None else str(default)),
               e(help_text), e("no limit" if default is None else str(default))))
    fixed = {k: v for k, v in eff.items() if k in settings.SPEC}
    script = SCRIPT % {
        "endpoint": json.dumps(ENDPOINT),
        "current": json.dumps(fixed, sort_keys=True),
        "defaults": json.dumps(defaults, sort_keys=True),
        "overridden": json.dumps(sorted(k for k in overrides if k in settings.SPEC)),
        "max_label": MAX_LABEL,
    }
    body = """<header><h1>brasenia rubric settings</h1>
<p class="sub">Household overrides for how the viewport decides. Changes are logged and applied by the
compositor within a few seconds; see the result on the <a href="%(base)s/viewport/rubric.html">rubric board</a>.
Leave a field empty, or put its default back, to drop the override.</p></header>
<form id="form">
%(fields)s
<div class="buttons"><button type="submit">Save</button>
<button type="button" id="reset" class="secondary">Reset every setting to its default</button></div>
<p class="muted">Resetting leaves the standing slots below; remove those one by one.</p>
</form>
<div id="status" class="muted"></div>
%(slots)s
<h2>How this works</h2>
<p class="muted">Each change is a line in <a href="%(base)s/signals/rubric.jsonl">signals/rubric.jsonl</a> on the
share, recorded by pub-signals with the time and the address it came from. The compositor applies the latest
valid line per setting and writes the result to <a href="%(base)s/viewport/rubric.json">viewport/rubric.json</a>.
A value it rejects shows under "Recent changes" on the rubric board and changes nothing.</p>""" % {
        "base": e(base), "fields": "\n".join(fields), "slots": _slots(eff, link_panes)}
    key = hashlib.sha1((body + script).encode("utf-8")).hexdigest()
    page = """<!doctype html>
<!-- configure:%(key)s -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>brasenia rubric settings</title>
<style>%(css)s</style>
</head>
<body>
<main>
%(body)s
</main>
<script>%(script)s</script>
</body>
</html>
""" % {"key": key, "css": CSS, "body": body, "script": script}
    return page, key


def _pane_field(key, label, help_text, current, overridden, resting):
    """A <select> of the live resting panes; unset, the first by id shows."""
    e = html.escape
    choices = [("", "None: the first resting pane by id")] + list(resting)
    if current and current not in {pid for pid, _ in resting}:
        choices.append((current, "%s (not on the bus now)" % current))
    options = "".join('<option value="%s"%s>%s</option>' % (
        e(pid), " selected" if (pid or None) == current else "", e(title)) for pid, title in choices)
    return ('<div class="field%s"><label for="%s">%s</label><select id="%s" name="%s">%s</select>'
            '<div class="help">%s <span class="default">Default: none.</span></div></div>'
            % (" overridden" if overridden else "", e(key), e(label), e(key), e(key), options, e(help_text)))


def _slots(eff, link_panes):
    """The standing slots (#97): one row per slot with a Remove button, then
    the form that adds one."""
    e = html.escape
    rows = []
    for pane_id, slot in settings.links(eff).items():
        src = slot["source"]
        rows.append('<tr><td><code>%s</code></td><td>%s</td><td><a href="%s">%s</a><br>'
                    '<span class="muted">%s</span></td>'
                    '<td><button type="button" class="secondary remove" data-id="%s">Remove</button></td></tr>'
                    % (e(pane_id), e(slot["title"]), e(src["url"]), e(src["url"]), e(src["theme"]),
                       e(settings.LINK_PREFIX + pane_id)))
    table = ('<table class="slots"><thead><tr><th>pane</th><th>title</th><th>page</th><th></th></tr></thead>'
             '<tbody>%s</tbody></table>' % "".join(rows)) if rows else '<p class="muted">No standing slots.</p>'
    state = ("Link panes are on." if link_panes else
             "Link panes are off until the renderer can show web pages safely; a slot added now waits "
             "on the rubric board as <em>off</em>.")
    return """<h2>Standing slots</h2>
<p class="muted">A standing slot keeps a web page on the wall as a resting pane, among the others: the
remote's Left/Right steps through it, and it can be the default. Pages that need a login, such as Grafana,
cannot be slots. %(state)s</p>
%(table)s
<form id="slot-form">
<div class="slot-fields">
<div><label for="slot-id">Pane id</label><input id="slot-id" required placeholder="pr-board" pattern="[a-z0-9][a-z0-9-]{0,62}"></div>
<div><label for="slot-title">Title</label><input id="slot-title" required maxlength="%(max_title)d" placeholder="Open pull requests"></div>
<div class="wide"><label for="slot-url">Page (http or https)</label><input id="slot-url" type="url" required placeholder="https://github.com/pulls"></div>
<div><label for="slot-theme">Theme</label><select id="slot-theme"><option value="dark">dark</option><option value="light">light</option></select></div>
</div>
<div class="buttons"><button type="submit">Add slot</button></div>
</form>
<div id="slot-status" class="muted"></div>""" % {"state": state, "table": table, "max_title": settings.MAX_TITLE}


def key_of(page_text):
    marker = "<!-- configure:"
    start = page_text.find(marker)
    if start < 0:
        return None
    end = page_text.find(" -->", start)
    return page_text[start + len(marker):end] if end > 0 else None
