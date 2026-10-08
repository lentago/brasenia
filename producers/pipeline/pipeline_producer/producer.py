"""One producer cycle: pipeline.json in, the change-pipeline pane out (or removed).

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/change-pipeline/``, every file is written ``x.partial`` →
``x`` with ``manifest.json`` last, and the directory is removed when the
activity resolves (nothing left in flight).
"""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from .document import DocumentError, in_flight, load, parse_ts, urllib_fetch
from .render import pane_title, render, restamp

PANE_ID = "change-pipeline"
STALE_AFTER = timedelta(minutes=5)
TTL_MINUTES = 15
AUTHOR = "pipeline-producer@pub"
ORIGIN = "operator"

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
    def __init__(self, webroot, url_base, fetch=urllib_fetch, clock=None):
        self.pane_dir = os.path.join(webroot, "viewport", "panes", PANE_ID)
        self.page_path = os.path.join(self.pane_dir, "pane.html")
        self.manifest_path = os.path.join(self.pane_dir, "manifest.json")
        self.url = url_base.rstrip("/") + "/viewport/pipeline.json"
        self.fetch = fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def cycle(self):
        now = self.clock()
        manifest = self._manifest()
        if manifest is UNKNOWN:
            return
        if manifest is not None and manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", PANE_ID, manifest.get("author"))
            return
        try:
            generated_at, repos = load(self.fetch, self.url)
        except DocumentError as err:
            log.info("pipeline.json %s; holding the pane", err)
            self._hold(manifest, now)
            return
        if now - generated_at > STALE_AFTER:
            log.info("pipeline.json is stale (generated_at %s); holding the pane",
                     generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
            self._hold(manifest, now)
            return

        flying = in_flight(repos)
        if not flying:
            self._remove("nothing in flight")
            return
        page = render(flying, generated_at, now)
        os.makedirs(self.pane_dir, exist_ok=True)
        write_atomic(self.page_path, page)
        write_atomic(self.manifest_path, json.dumps({
            "schema": 1,
            "class": "activity",
            "title": pane_title(len(flying)),
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
        }, indent=2, ensure_ascii=False) + "\n")
        log.info("%s: %s", PANE_ID, ", ".join(str(r.get("repo")) for r in flying))

    def _hold(self, manifest, now):
        """No fresh data: keep the pane as it is until its TTL, restamped; never renew it."""
        if manifest is None:
            if os.path.isdir(self.pane_dir):
                self._remove("no manifest and no fresh data")  # a write this producer never finished
            return
        try:
            expires = parse_ts(manifest["created"]) + timedelta(minutes=float(manifest["ttl_minutes"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            expires = now
        if now >= expires:
            self._remove("expired without fresh data")
            return
        try:
            with open(self.page_path, encoding="utf-8") as fh:
                old = fh.read()
        except OSError:
            return
        page = restamp(old, now)
        if page is not None and page != old:
            write_atomic(self.page_path, page)

    def _manifest(self):
        """Our pane's manifest; None when absent; UNKNOWN when it cannot be read or parsed.

        Writes are atomic (write-then-rename), so an unreadable manifest is
        never "half-written by us": it is someone else's, a permission
        problem, or corruption, and the cycle leaves the pane alone.
        """
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
