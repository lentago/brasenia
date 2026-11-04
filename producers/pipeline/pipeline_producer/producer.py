"""One producer cycle: pipeline.json in, the change-pipeline pane out (or removed).

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/change-pipeline/``, a new pane is built in ``staging/`` and
renamed in whole (ADR-0022), an existing one rewritten ``x.partial`` → ``x``
with ``manifest.json`` last, and the directory is removed when the activity
resolves (nothing left in flight).
"""

import errno
import json
import logging
import os
import secrets
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


def staging_path(bus, pane_id, tag):
    """A fresh name in ``staging/``, the bus's scratch directory beside
    ``panes/``, where a pane is built before it appears and taken apart after
    it leaves (ADR-0022)."""
    staging = os.path.join(bus, "staging")
    os.makedirs(staging, exist_ok=True)
    return os.path.join(staging, "%s.%s.%s" % (pane_id, tag, secrets.token_hex(6)))


def create_pane(bus, pane_dir, files):
    """Create ``pane_dir`` holding ``files`` ((name, text or bytes) pairs,
    manifest last), in one step. Return False, writing nothing, when it
    already exists.

    The pane is built in ``staging/`` and renamed into place. A rename onto a
    directory that holds files fails, so of two writers creating the same pane
    at once exactly one succeeds, and no reader sees it half-written
    (ADR-0022)."""
    os.makedirs(os.path.dirname(pane_dir), exist_ok=True)
    tmp = staging_path(bus, os.path.basename(pane_dir), "new")
    os.mkdir(tmp)
    try:
        for name, data in files:
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
        os.rename(tmp, pane_dir)
        return True
    except OSError as exc:
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return False
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # gone already after the rename


def remove_pane(bus, pane_dir):
    """Take a pane off the bus in one step: rename it into ``staging/``, then
    delete it there, so nobody sees it half-deleted (ADR-0022)."""
    gone = staging_path(bus, os.path.basename(pane_dir), "gone")
    try:
        os.rename(pane_dir, gone)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EBUSY):
            raise
        shutil.rmtree(pane_dir)  # panes/ is not on staging/'s filesystem
        return
    shutil.rmtree(gone)


# Returned by _manifest when the pane directory holds a manifest this producer
# cannot read or parse; the cycle then changes nothing.
UNKNOWN = object()


class Producer:
    def __init__(self, webroot, url_base, fetch=urllib_fetch, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.pane_dir = os.path.join(self.bus, "panes", PANE_ID)
        self.page_path = os.path.join(self.pane_dir, "pane.html")
        self.manifest_path = os.path.join(self.pane_dir, "manifest.json")
        self.url = url_base.rstrip("/") + "/viewport/pipeline.json"
        self.fetch = fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def cycle(self):
        now = self.clock()
        manifest = self._manifest()
        if not self._ours(manifest):
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
        files = [("pane.html", page),
                 ("manifest.json", json.dumps({
                     "schema": 1,
                     "class": "activity",
                     "title": pane_title(len(flying)),
                     "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "ttl_minutes": TTL_MINUTES,
                     "author": AUTHOR,
                     "origin": ORIGIN,
                 }, indent=2, ensure_ascii=False) + "\n")]
        # A new pane appears whole or not at all; when another writer creates
        # it first, the ownership check runs again on the pane that won.
        if os.path.isdir(self.pane_dir) or not create_pane(self.bus, self.pane_dir, files):
            if not self._ours(self._manifest()):
                return
            for name, text in files:
                write_atomic(os.path.join(self.pane_dir, name), text)
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

    def _ours(self, manifest):
        """True when the pane is absent or this producer's; logs why not otherwise."""
        if manifest is UNKNOWN:
            return False
        if manifest is not None and manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", PANE_ID, manifest.get("author"))
            return False
        return True

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
            try:
                remove_pane(self.bus, self.pane_dir)
            except OSError as err:
                log.warning("could not remove panes/%s (%s)", PANE_ID, err)
