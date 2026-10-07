"""The filesystem half: scan the pane bus, persist state, publish the pointer.

The compositor writes only its own files (``current.json``, ``status.html``
and ``state/``), each with write-then-rename. Pane directories are read, never
modified or deleted.
"""

import html
import json
import os

from . import rubric

STATE_FILE = "compositor.json"


def paths(webroot):
    viewport = os.path.join(webroot, "viewport")
    return {
        "viewport": viewport,
        "panes": os.path.join(viewport, "panes"),
        "focus": os.path.join(viewport, "focus"),
        "state": os.path.join(viewport, "state"),
        "current": os.path.join(viewport, "current.json"),
        "status": os.path.join(viewport, "status.html"),
        "brief": os.path.join(webroot, "brief", "index.html"),
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
  pane or the morning brief is published.</p>
</main>
</body>
</html>
"""


def render_status(pointer):
    """The fallback of last resort, to the pane contract: 1280x720, dark,
    text >= 20 px, and the bottom-right 220x50 px left clear (the bottom
    padding keeps every line above the clock overlay)."""
    decided = rubric.parse_time(pointer["decided_at"]).astimezone()
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


def tick(webroot, url_base, state, now, log=print):
    """Scan, decide and publish once; return the next state.

    ``current.json`` is rewritten only when the decision changes (or when the
    file is missing); ``status.html`` is written just before a status
    pointer is published, so the pointer never names a missing page.
    """
    p = paths(webroot)
    ensure_dirs(p)
    pointer, new_state = rubric.decide(
        scan(p["panes"]), now, state,
        brief_present=os.path.isfile(p["brief"]), url_base=url_base)

    old_skipped = state.get("skipped") or {}
    for pane_id, reason in sorted(new_state["skipped"].items()):
        if old_skipped.get(pane_id) != reason:
            log("skipped: pane=%s (%s)" % (pane_id, reason))

    changed = pointer is not state.get("pointer")
    if changed or not os.path.exists(p["current"]):
        if pointer["fallback"] == "status":
            atomic_write(p["status"], render_status(pointer))
        atomic_write(p["current"], json.dumps(pointer, indent=2) + "\n")
        if changed:
            log(describe(pointer))
    if new_state != state:
        save_state(p["state"], new_state)
    return new_state
