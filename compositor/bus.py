"""The filesystem half: scan the pane bus, persist state, publish the pointer.

The compositor writes only its own files (``current.json``, ``status.html``,
``rubric.html``, ``rubric.json``, ``configure.html``, ``lineup.json`` and
``state/``), each with
write-then-rename. Pane directories and the configurator's signal log
(``signals/rubric.jsonl``, ADR-0011) are read, never modified or deleted.
"""

import hashlib
import html
import json
import os
import time
from datetime import datetime, timezone

from . import board, configure, rubric, settings

STATE_FILE = "compositor.json"
BOARD_MAX_AGE_S = 60   # rewrite an unchanged board this often, so its clock stays honest

# path -> (identity, rev): a page is re-read only when it was rewritten, not
# on every tick over the share. identity is (inode, mtime, ctime, size), and
# writers replace pages by rename, so a rewrite almost always changes it. The
# exception is a rewrite inside the file-time granularity of the one hashed, so
# (as git does for its index) a hash taken within REV_RACY_S of the file's
# mtime is not trusted and the page is hashed again on the next tick.
_REV_CACHE = {}
REV_RACY_S = 2


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
        "lineup": os.path.join(viewport, "lineup.json"),
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


def page_rev(path):
    """A page's revision (#96): the first 12 hex digits of the SHA-256 of its
    bytes, or None when it cannot be read. Producers rewrite their pages on a
    timer whether or not anything changed, so the file's time is no use."""
    try:
        st = os.stat(path)
    except OSError:
        _REV_CACHE.pop(path, None)
        return None
    identity = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    cached = _REV_CACHE.get(path)
    if cached and cached[0] == identity:
        return cached[1]
    try:
        with open(path, "rb") as f:
            rev = hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return None
    if time.time() - st.st_mtime_ns / 1e9 >= REV_RACY_S:
        _REV_CACHE[path] = (identity, rev)
    else:
        _REV_CACHE.pop(path, None)
    return rev


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
        entry = {"id": name, "files": files, "manifest": None, "rev": None}
        if "manifest.json" in files:
            entry["manifest"] = _read_manifest(
                os.path.join(pane_dir, "manifest.json"))
        if "pane.html" in files:
            entry["rev"] = page_rev(os.path.join(pane_dir, "pane.html"))
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
<meta name="brasenia-canvas" content="1920x1080">
<title>brasenia status</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #0e1612; }}
  body {{ width: 1920px; height: 1080px; overflow: hidden; color: #d8e4dc;
         font: 42px/1.4 system-ui, sans-serif; }}
  main {{ box-sizing: border-box; width: 1920px; height: 1080px;
         padding: 36px 36px 111px 36px; display: flex; flex-direction: column;
         justify-content: center; }}
  h1 {{ margin: 0 0 36px 0; font-size: 66px; color: #e0a81c; }}
  p {{ margin: 0 0 24px 0; max-width: 1500px; }}
  .meta {{ font-size: 33px; color: #8fa89a; }}
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
    """The fallback of last resort, to the pane contract: 1920x1080, dark,
    text >= 30 px, and the bottom-right 330x75 px left clear (the bottom
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
    return line


def _shown(pointer):
    """What a pointer puts on screen, for the decision log: a new revision of
    the same pane or a renewed expiry is not worth a line."""
    return {k: v for k, v in pointer.items() if k not in ("decided_at", "expires_at", "rev")}


def tick(webroot, url_base, state, now, log=print, tz=None, link_panes=False):
    """Scan, decide and publish once; return the next state. Times on the
    status card and the board are shown in ``tz`` (None: the host's zone).
    Link panes are shown only with ``link_panes`` (ADR-0016).

    ``current.json`` is rewritten only when the pointer changes (or when the
    file is missing); ``status.html`` is written just before a status
    pointer is published, so the pointer never names a missing page.
    """
    p = paths(webroot)
    ensure_dirs(p)
    entries = scan(p["panes"])
    overrides, history = settings.load(p["signals"])
    eff = settings.effective(overrides)
    priority = settings.priorities(eff)
    brief = _brief(p["briefing"], p["briefing_manifest"])
    brief_ok, brief_why = settings.brief_usable(brief, eff, now)
    default_pane = eff["default.pane"]
    pointer, new_state = rubric.decide(
        entries, now, state, brief_present=brief_ok, url_base=url_base,
        priority=priority, briefing_title=brief["title"],
        default_pane=default_pane, link_panes=link_panes, brief_rev=brief["rev"])

    old_skipped = state.get("skipped") or {}
    for pane_id, reason in sorted(new_state["skipped"].items()):
        if old_skipped.get(pane_id) != reason:
            log("skipped: pane=%s (%s)" % (pane_id, reason))

    previous = state.get("pointer")
    changed = pointer is not previous
    # The status page is recreated whenever the status pointer is active and
    # the file is missing, not only on a decision change: a deleted
    # status.html must never leave current.json naming an absent page.
    if pointer["fallback"] == "status" and (changed or not os.path.isfile(p["status"])):
        atomic_write(p["status"], render_status(pointer, tz))
    if changed or not os.path.exists(p["current"]):
        atomic_write(p["current"], json.dumps(pointer, indent=2) + "\n")
        if changed and (previous is None or _shown(pointer) != _shown(previous)):
            log(describe(pointer))
    if new_state != state:
        save_state(p["state"], new_state)
    write_settings(p["settings"], settings.document(eff, overrides, history), log)
    rows = rubric.explain(entries, now, pointer, priority, default_pane=default_pane,
                          link_panes=link_panes, arrivals=new_state["arrivals"])
    resting = [(r["id"], r["title"]) for r in rows
               if r.get("class") == "ambient" and r["status"] in ("showing", "outranked")]
    page, key = configure.render(eff, overrides, url_base, resting, link_panes)
    _write_if_changed(p["configure"], page, key, configure.key_of)
    view = {"effective": eff, "overrides": overrides, "history": history,
            "brief_ok": brief_ok, "brief_why": brief_why, "link_panes": link_panes}
    write_board(p["board"], pointer, rows, brief, now, url_base, tz, view)
    _write_json_if_changed(p["lineup"], lineup(pointer, rows, brief, url_base, default_pane))
    return new_state


BRIEFING_ID = "_briefing"   # not a valid pane id, so it can never collide with one


def lineup(pointer, rows, brief, url_base, default_pane=None):
    """The body of ``viewport/lineup.json``: what a client may step through
    (the Roku remote's peek, ADR-0012). Live panes in rubric order, the one on
    screen marked, then the briefing slot when it exists and no live pane
    already carries the same brief. A client only looks; this changes nothing
    the compositor decides. Each item carries its ``rev``, and a link pane its
    ``source``, so a client can tell when to render again (#96)."""
    base = url_base.rstrip("/")
    items = [{"id": r["id"], "title": r["title"], "class": r["class"],
              "priority": r["priority"], "showing": r["status"] == "showing",
              "default": r["id"] == default_pane and r["class"] == "ambient",
              "url": rubric.pane_url(r, base), "rev": r.get("rev"),
              "source": r.get("source")}
             for r in rows if r["status"] in ("showing", "outranked")]
    if brief["present"] and brief.get("pane") not in {i["id"] for i in items}:
        items.append({"id": BRIEFING_ID, "title": brief["title"], "class": "briefing",
                      "priority": rubric.PRIORITY["briefing"],
                      "showing": pointer.get("fallback") == "briefing", "default": False,
                      "url": base + rubric.BRIEFING_PATH, "rev": brief.get("rev"),
                      "source": None})
    return {"schema": 1, "decided_at": pointer["decided_at"], "items": items}


def _write_json_if_changed(path, doc):
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    atomic_write(path, text)


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
    log("settings: %s" % (", ".join("%s=%s" % (k, v["source"]["url"] if settings.is_link(k) else v)
                                    for k, v in sorted(doc["overrides"].items()))
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
    every minute whatever the brief's age. ``rev`` is the page's revision."""
    if not os.path.isfile(page):
        return {"present": False, "mtime": None, "title": rubric.BRIEFING_TITLE, "pane": None,
                "rev": None}
    manifest = _read_manifest(manifest_path)
    if not isinstance(manifest, dict):
        manifest = {}
    title = manifest.get("title")
    try:
        published = rubric.parse_time(manifest.get("published"))
    except (ValueError, OverflowError):
        published = datetime.fromtimestamp(os.path.getmtime(page), timezone.utc)
    pane = manifest.get("pane")
    return {"present": True, "mtime": published,
            "title": title if isinstance(title, str) and title.strip() else rubric.BRIEFING_TITLE,
            "pane": pane if isinstance(pane, str) else None, "rev": page_rev(page)}


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
