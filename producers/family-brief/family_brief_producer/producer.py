"""One producer cycle: the Family Brief document in, the family pane out (or removed).

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/family-today/``, every file is written ``x.partial`` → ``x``
with ``manifest.json`` last, and the directory is removed when the brief is
no longer fresh (older than yesterday), so the wall falls back on its own.
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .document import DocumentError, is_fresh, load, urllib_fetch
from .render import render

PANE_ID = "family-today"
PANE_CLASS = "ambient"
TTL_MINUTES = 30
AUTHOR = "family-brief-producer@pub"
ORIGIN = "operator"
TITLE = "Family: today and tomorrow"
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


class Producer:
    def __init__(self, webroot, source=DEFAULT_SOURCE, tz=DEFAULT_TZ, fetch=urllib_fetch, clock=None):
        self.pane_dir = os.path.join(webroot, "viewport", "panes", PANE_ID)
        self.page_path = os.path.join(self.pane_dir, "pane.html")
        self.manifest_path = os.path.join(self.pane_dir, "manifest.json")
        self.source = source
        self.tz = ZoneInfo(tz)
        self.fetch = fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def cycle(self):
        now = self.clock()
        today = now.astimezone(self.tz).date()
        manifest = self._manifest()
        if manifest is UNKNOWN:
            return
        if manifest is not None and manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", PANE_ID, manifest.get("author"))
            return
        try:
            doc = load(self.fetch, self.source)
        except DocumentError as err:
            # Keep what is up; the TTL takes it down if the source stays away.
            log.info("family brief %s; leaving the pane to its TTL", err)
            return
        if not is_fresh(doc, today):
            self._remove("brief of %s is older than yesterday" % doc["date"])
            return
        os.makedirs(self.pane_dir, exist_ok=True)
        write_atomic(self.page_path, render(doc, today, now, self.tz))
        write_atomic(self.manifest_path, json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": TITLE,
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
        }, indent=2, ensure_ascii=False) + "\n")
        log.info("%s: brief of %s rendered for %s", PANE_ID, doc["date"], today.isoformat())

    def _manifest(self):
        """Our pane's manifest; None when absent; UNKNOWN when it cannot be read or parsed."""
        try:
            with open(self.manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as err:
            log.warning("panes/%s/manifest.json cannot be read (%s); leaving the pane alone", PANE_ID, err)
            return UNKNOWN
        if not isinstance(manifest, dict):
            log.warning("panes/%s/manifest.json is not an object; leaving the pane alone", PANE_ID)
            return UNKNOWN
        return manifest

    def _remove(self, why):
        if os.path.isdir(self.pane_dir):
            log.info("removing panes/%s (%s)", PANE_ID, why)
            shutil.rmtree(self.pane_dir, ignore_errors=True)
