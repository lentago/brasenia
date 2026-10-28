"""The filesystem half: scan the pane bus, persist state, publish the pointer.

The compositor writes only its own files (``current.json``, ``status.html``,
``rubric.html``, ``rubric.json``, ``configure.html`` and ``state/``), each with
write-then-rename. Pane directories and the configurator's signal log
(``signals/rubric.jsonl``, ADR-0011) are read, never modified or deleted.
"""

import html
import json
import os
from datetime import datetime, timezone

from . import board, configure, rubric, settings

STATE_FILE = "compositor.json"
BOARD_MAX_AGE_S = 60   # rewrite an unchanged board this often, so its clock stays honest


def paths(webroot):
    viewport = os.path.join(webroot, "viewport")
    return {
        "viewport": viewport,
        "panes": os.path.join(viewport, "panes"),
        "focus": os.path.join(viewport, "focus"),
        "state": os.path.join(viewport, "state"),
        "current": os.path.join(viewport, "current.json"),
        "status": os.path.join(viewport, "status.html"),
        "board": os.path.join(viewport, "rubric.html"),
        "settings": os.path.join(viewport, "rubric.json"),
        "configure": os.path.join(viewport, "configure.html"),
        "signals": os.path.join(webroot, "signals", "rubric.jsonl"),
        "briefing": os.path.join(viewport, "briefing", "pane.html"),
        "briefing_manifest": os.path.join(viewport, "briefing", "manifest.json"),
    }


def ensure_dirs(p):
    for key in ("panes", "focus", "state"):
        os.makedirs(p[key], exist_ok=True)


def atomic_write(path, text):
    """Write ``path`` via ``path.partial`` and a rename, so readers never see
    a half-written file."""
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(partial, path)


def _read_manifest(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return rubric.Malformed("manifest does not parse: %s" % exc)


def scan(panes_dir):
    """Return the pane set ``rubric.decide`` expects, one entry per directory."""
    entries = []
    try:
        names = sorted(os.listdir(panes_dir))
    except FileNotFoundError:
        return entries
    for name in names:
        pane_dir = os.path.join(panes_dir, name)
        if not os.path.isdir(pane_dir):
            continue
        try:
            files = set(os.listdir(pane_dir))
        except OSError:
            continue  # removed mid-scan: the writer relinquished
        entry = {"id": name, "files": files, "manifest": None}
        if "manifest.json" in files:
            entry["manifest"] = _read_manifest(
                os.path.join(pane_dir, "manifest.json"))
        entries.append(entry)
    return entries


def load_state(state_dir):
    try:
        with open(os.path.join(state_dir, STATE_FILE), encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state_dir, state):
    atomic_write(os.path.join(state_dir, STATE_FILE),
                 json.dumps(state, indent=2, sort_keys=True) + "\n")


STATUS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>brasenia status</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #0e1612; }}
  body {{ width: 1280px; height: 720px; overflow: hidden; color: #d8e4dc;
         font: 28px/1.4 system-ui, sans-serif; }}
  main {{ box-sizing: border-box; width: 1280px; height: 720px;
         padding: 24px 24px 74px 24px; display: flex; flex-direction: column;
         justify-content: center; }}
  h1 {{ margin: 0 0 24px 0; font-size: 44px; color: #e0a81c; }}
  p {{ margin: 0 0 16px 0; max-width: 1000px; }}
  .meta {{ font-size: 22px; color: #8fa89a; }}
</style>
</head>
<body>
<main>
  <h1>brasenia</h1>
  <p>{reason}</p>
  <p class="meta">Status since {since}. The display returns on its own when a
  pane or the briefing is published.</p>
</main>
</body>
</html>
"""


def render_status(pointer, tz=None):
    """The fallback of last resort, to the pane contract: 1280x720, dark,
    text >= 20 px, and the bottom-right 220x50 px left clear (the bottom
    padding keeps every line above the clock overlay)."""
    decided = rubric.parse_time(pointer["decided_at"]).astimezone(tz)
    return STATUS_HTML.format(
        reason=html.escape(pointer["title"]),
        since=html.escape(decided.strftime("%H:%M %Z (%Y-%m-%d)")))


def describe(pointer):
    """The one log line for a decision change."""
    if pointer["fallback"]:
        return "decision: fallback=%s url=%s (%s)" % (
            pointer["fallback"], pointer["url"], pointer["title"])
    line = "decision: pane=%s class=%s priority=%d expires_at=%s" % (
        pointer["pane"], pointer["class"], pointer["priority"],
        pointer["expires_at"])
    if pointer["rotation"]:
        r = pointer["rotation"]
        line += " rotation=%d/%d dwell_s=%s" % (r["index"] + 1, r["of"],
                                               r["dwell_s"])
    return line


def tick(webroot, url_base, state, now, log=print, tz=None):
    """Scan, decide and publish once; return the next state. Times on the
    status card and the board are shown in ``tz`` (None: the host's zone).

    ``current.json`` is rewritten only when the decision changes (or when the
    file is missing); ``status.html`` is written just before a status
    pointer is published, so the pointer never names a missing page.
    """
    p = paths(webroot)
    ensure_dirs(p)
    entries = scan(p["panes"])
    overrides, history = settings.load(p["signals"])
    eff = settings.effective(overrides)
    priority, dwell = settings.priorities(eff), eff["rotation.dwell_s"]
    brief = _brief(p["briefing"], p["briefing_manifest"])
    brief_ok, brief_why = settings.brief_usable(brief, eff, now)
    pointer, new_state = rubric.decide(
        entries, now, state, brief_present=brief_ok, url_base=url_base,
        priority=priority, default_dwell=dwell, briefing_title=brief["title"])

    old_skipped = state.get("skipped") or {}
    for pane_id, reason in sorted(new_state["skipped"].items()):
        if old_skipped.get(pane_id) != reason:
            log("skipped: pane=%s (%s)" % (pane_id, reason))

    changed = pointer is not state.get("pointer")
    # The status page is recreated whenever the status pointer is active and
    # the file is missing, not only on a decision change: a deleted
    # status.html must never leave current.json naming an absent page.
    if pointer["fallback"] == "status" and (changed or not os.path.isfile(p["status"])):
        atomic_write(p["status"], render_status(pointer, tz))
    if changed or not os.path.exists(p["current"]):
        atomic_write(p["current"], json.dumps(pointer, indent=2) + "\n")
        if changed:
            log(describe(pointer))
    if new_state != state:
        save_state(p["state"], new_state)
    write_settings(p["settings"], settings.document(eff, overrides, history), log)
    page, key = configure.render(eff, overrides, url_base)
    _write_if_changed(p["configure"], page, key, configure.key_of)
    view = {"effective": eff, "overrides": overrides, "history": history,
            "brief_ok": brief_ok, "brief_why": brief_why}
    write_board(p["board"], pointer,
                rubric.explain(entries, now, pointer, priority, dwell),
                brief, now, url_base, tz, view)
    return new_state


def write_settings(path, doc, log=print):
    """Write ``rubric.json`` (the effective settings) when it changes, with one
    log line naming the overrides now in force."""
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = None
    if old == text:
        return
    atomic_write(path, text)
    if old is None and not doc["overrides"]:
        return  # first write, nothing overridden: nothing worth a log line
    log("settings: %s" % (", ".join("%s=%s" % kv for kv in sorted(doc["overrides"].items()))
                          or "all defaults"))


def _write_if_changed(path, page, key, key_of):
    try:
        with open(path, encoding="utf-8") as f:
            if key_of(f.read(200)) == key:
                return
    except OSError:
        pass
    atomic_write(path, page)


def _brief(page, manifest_path):
    """The briefing slot (``viewport/briefing/``, brasenia#76): whether its page
    exists, its title, and when the brief was published. The age comes from
    the manifest's ``published``, not the file: the producer rewrites the page
    every minute whatever the brief's age."""
    if not os.path.isfile(page):
        return {"present": False, "mtime": None, "title": rubric.BRIEFING_TITLE}
    manifest = _read_manifest(manifest_path)
    if not isinstance(manifest, dict):
        manifest = {}
    title = manifest.get("title")
    try:
        published = rubric.parse_time(manifest.get("published"))
    except (ValueError, OverflowError):
        published = datetime.fromtimestamp(os.path.getmtime(page), timezone.utc)
    return {"present": True, "mtime": published,
            "title": title if isinstance(title, str) and title.strip() else rubric.BRIEFING_TITLE}


def write_board(path, pointer, rows, brief, now, url_base, tz=None, view=None):
    """Write ``rubric.html`` when its content changed, or when it is
    ``BOARD_MAX_AGE_S`` old, so a 5 s loop does not rewrite it every tick."""
    page, key = board.render(pointer, rows, brief, now, url_base, tz, view)
    try:
        with open(path, encoding="utf-8") as f:
            old_key = board.key_of(f.read(200))
        age = now.timestamp() - os.path.getmtime(path)
    except OSError:
        old_key, age = None, None
    if key != old_key or age is None or not 0 <= age < BOARD_MAX_AGE_S:
        atomic_write(path, page)
