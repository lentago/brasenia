"""One producer cycle: the Family Brief document in, the family pane out (or removed).

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/family-today/``, every file is written ``x.partial`` → ``x``
with ``manifest.json`` last, and the directory is removed when the brief is
no longer fresh (older than yesterday), so the wall falls back on its own.
Beside ``pane.html`` sits ``detail.html``, the desk edition a client pins to
by URL (the office Roku); the compositor never reads it.

The producer also keeps the **briefing slot**, ``viewport/briefing/``
(``pane.html``, ``detail.html``, ``manifest.json``): the latest brief rendered
whatever its age, which the compositor falls back to when nothing on the bus
is live. The pane goes when the brief is older than yesterday; the slot stays,
saying how old it is, and the compositor's ``briefing.max_age_hours`` setting
decides whether it is still worth showing (brasenia#76).
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .document import DocumentError, is_fresh, load, parse_ts, urllib_fetch
from .detail import render_detail
from .render import render
from .week import render_week, render_week_detail

PANE_ID = "family-today"
PANE_CLASS = "ambient"
TTL_MINUTES = 30
AUTHOR = "family-brief-producer@pub"
ORIGIN = "operator"
TITLE = "Family: today and tomorrow"
WEEK_ID = "family-week"
WEEK_TITLE = "Family: this week"
# Both are resting panes; with no household default they share the rung and
# take turns, slowly (#83).
DWELL_S = 60
BRIEFING_TITLE = "Family Brief"
DEFAULT_SOURCE = "http://pub.lan/family-brief/latest.json"
DEFAULT_TZ = "America/New_York"

log = logging.getLogger(__name__)


def write_atomic(path, text):
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(partial, path)


# Returned by _manifest when the pane directory holds a manifest this producer
# cannot read or parse; the cycle then changes nothing.
UNKNOWN = object()


# (pane id, title, wall renderer, desk renderer)
PANES = (
    (PANE_ID, TITLE, render, render_detail),
    (WEEK_ID, WEEK_TITLE, render_week, render_week_detail),
)


class Producer:
    def __init__(self, webroot, source=DEFAULT_SOURCE, tz=DEFAULT_TZ, fetch=urllib_fetch, clock=None):
        self.panes_dir = os.path.join(webroot, "viewport", "panes")
        self.briefing_dir = os.path.join(webroot, "viewport", "briefing")
        self.source = source
        self.tz = ZoneInfo(tz)
        self.fetch = fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def cycle(self):
        now = self.clock()
        today = now.astimezone(self.tz).date()
        try:
            doc = load(self.fetch, self.source)
        except DocumentError as err:
            # Keep what is up; the TTL takes it down if the source stays away.
            log.info("family brief %s; leaving the pane to its TTL", err)
            return
        self._briefing(doc, today, now)
        fresh = is_fresh(doc, today)
        for pane_id, title, page, detail in PANES:
            self._pane(pane_id, title, page, detail, doc, today, now, fresh)

    def _pane(self, pane_id, title, page, detail, doc, today, now, fresh):
        """Write (or, once the brief is stale, remove) one of this producer's panes."""
        pane_dir = os.path.join(self.panes_dir, pane_id)
        manifest_path = os.path.join(pane_dir, "manifest.json")
        manifest = _read_manifest(manifest_path, "panes/%s/manifest.json" % pane_id)
        if manifest is UNKNOWN:
            return
        if manifest is not None and manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", pane_id, manifest.get("author"))
            return
        if not fresh:
            self._remove(pane_dir, pane_id, "brief of %s is older than yesterday" % doc["date"])
            return
        os.makedirs(pane_dir, exist_ok=True)
        write_atomic(os.path.join(pane_dir, "pane.html"), page(doc, today, now, self.tz))
        write_atomic(os.path.join(pane_dir, "detail.html"), detail(doc, today, now, self.tz))
        write_atomic(manifest_path, json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": title,
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
            "dwell_s": DWELL_S,
        }, indent=2, ensure_ascii=False) + "\n")
        log.info("%s: brief of %s rendered for %s", pane_id, doc["date"], today.isoformat())

    def _briefing(self, doc, today, now):
        """Render the brief into the briefing slot, whatever its age."""
        path = os.path.join(self.briefing_dir, "manifest.json")
        owner = _read_manifest(path, "briefing/manifest.json")
        if owner is UNKNOWN:
            return
        if owner is not None and owner.get("author") != AUTHOR:
            log.warning("viewport/briefing belongs to %r; leaving it alone", owner.get("author"))
            return
        os.makedirs(self.briefing_dir, exist_ok=True)
        write_atomic(os.path.join(self.briefing_dir, "pane.html"), render(doc, today, now, self.tz))
        write_atomic(os.path.join(self.briefing_dir, "detail.html"),
                     render_detail(doc, today, now, self.tz))
        write_atomic(path, json.dumps({
            "schema": 1,
            "title": BRIEFING_TITLE,
            "published": _published(doc),
            "author": AUTHOR,
            # The live pane that carries this same brief; the compositor's
            # line-up skips the slot while that pane is on the bus.
            "pane": PANE_ID,
        }, indent=2, ensure_ascii=False) + "\n")

    def _remove(self, pane_dir, pane_id, why):
        if os.path.isdir(pane_dir):
            log.info("removing panes/%s (%s)", pane_id, why)
            shutil.rmtree(pane_dir, ignore_errors=True)

def _read_manifest(path, name):
    """A manifest dict; None when absent; UNKNOWN when it cannot be read or parsed."""
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        log.warning("%s cannot be read (%s); leaving it alone", name, err)
        return UNKNOWN
    if not isinstance(manifest, dict):
        log.warning("%s is not an object; leaving it alone", name)
        return UNKNOWN
    return manifest


def _published(doc):
    """When the brief was generated (``generated_at``), else midnight UTC on its date."""
    try:
        return parse_ts(doc.get("generated_at")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, AttributeError):
        return doc["date"] + "T00:00:00Z"
