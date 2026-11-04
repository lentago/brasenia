"""One producer cycle: the Family Brief document in, the family pane out (or removed).

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/family-today/``, a new pane is built in ``staging/`` and
renamed in whole (ADR-0022), an existing one rewritten ``x.partial`` → ``x``
with ``manifest.json`` last, and the directory is removed when the brief is no
longer fresh (older than yesterday), so the wall falls back on its own. Each
pane is one ``pane.html`` on the 1920×1080 canvas (brasenia ADR-0019), one band
(ADR-0020). The ``detail.html`` desk editions are retired, because they were
below the canvas's 30 px floor; one left by an older producer is removed.

The producer also keeps the **briefing slot**, ``viewport/briefing/``
(``pane.html``, ``manifest.json``): the latest brief rendered
whatever its age, which the compositor falls back to when nothing on the bus
is live. The pane goes when the brief is older than yesterday; the slot stays,
saying how old it is, and the compositor's ``briefing.max_age_hours`` setting
decides whether it is still worth showing (brasenia#76).
"""

import errno
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .document import DocumentError, is_fresh, load, parse_ts, urllib_fetch
from .render import render
from .week import render_week

PANE_ID = "family-today"
PANE_CLASS = "ambient"
TTL_MINUTES = 30
AUTHOR = "family-brief-producer@pub"
ORIGIN = "operator"
TITLE = "Family: today and tomorrow"
WEEK_ID = "family-week"
WEEK_TITLE = "Family: this week"
# Both are resting panes; with no household default they share the rung and
# the first by id shows (ADR-0020). The compositor ignores dwell_s; it stays
# in the manifest for Contracts v1.
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


# (pane id, title, renderer)
PANES = (
    (PANE_ID, TITLE, render),
    (WEEK_ID, WEEK_TITLE, render_week),
)


class Producer:
    def __init__(self, webroot, source=DEFAULT_SOURCE, tz=DEFAULT_TZ, fetch=urllib_fetch, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.panes_dir = os.path.join(self.bus, "panes")
        self.briefing_dir = os.path.join(self.bus, "briefing")
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
        for pane_id, title, page in PANES:
            self._pane(pane_id, title, page, doc, today, now, fresh)

    def _pane(self, pane_id, title, page, doc, today, now, fresh):
        """Write (or, once the brief is stale, remove) one of this producer's panes."""
        pane_dir = os.path.join(self.panes_dir, pane_id)
        manifest_path = os.path.join(pane_dir, "manifest.json")

        def ours():
            manifest = _read_manifest(manifest_path, "panes/%s/manifest.json" % pane_id)
            if manifest is UNKNOWN:
                return False
            if manifest is not None and manifest.get("author") != AUTHOR:
                log.warning("panes/%s belongs to %r; leaving it alone", pane_id, manifest.get("author"))
                return False
            return True

        if not ours():
            return
        if not fresh:
            self._remove(pane_dir, pane_id, "brief of %s is older than yesterday" % doc["date"])
            return
        if not self._put(pane_dir, [
                ("pane.html", page(doc, today, now, self.tz)),
                ("manifest.json", json.dumps({
                    "schema": 1,
                    "class": PANE_CLASS,
                    "title": title,
                    "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ttl_minutes": TTL_MINUTES,
                    "author": AUTHOR,
                    "origin": ORIGIN,
                    "dwell_s": DWELL_S,
                }, indent=2, ensure_ascii=False) + "\n")], ours):
            return
        log.info("%s: brief of %s rendered for %s", pane_id, doc["date"], today.isoformat())

    def _briefing(self, doc, today, now):
        """Render the brief into the briefing slot, whatever its age."""
        path = os.path.join(self.briefing_dir, "manifest.json")

        def ours():
            owner = _read_manifest(path, "briefing/manifest.json")
            if owner is UNKNOWN:
                return False
            if owner is not None and owner.get("author") != AUTHOR:
                log.warning("viewport/briefing belongs to %r; leaving it alone", owner.get("author"))
                return False
            return True

        if not ours():
            return
        self._put(self.briefing_dir, [
            ("pane.html", render(doc, today, now, self.tz)),
            ("manifest.json", json.dumps({
                "schema": 1,
                "title": BRIEFING_TITLE,
                "published": _published(doc),
                "author": AUTHOR,
                # The live pane that carries this same brief; the compositor's
                # line-up skips the slot while that pane is on the bus.
                "pane": PANE_ID,
            }, indent=2, ensure_ascii=False) + "\n")], ours)

    def _put(self, directory, files, ours):
        """Write ``files`` (manifest last) as the pane at ``directory``; False
        when someone else's pane is there. A new pane appears whole in one
        rename; when another writer creates it first, ``ours`` runs again on
        the pane that won. An existing pane is rewritten file by file."""
        if not os.path.isdir(directory) and create_pane(self.bus, directory, files):
            return True
        if not ours():
            return False
        for name, text in files[:-1]:
            write_atomic(os.path.join(directory, name), text)
        _drop_desk_edition(directory)
        write_atomic(os.path.join(directory, files[-1][0]), files[-1][1])
        return True

    def _remove(self, pane_dir, pane_id, why):
        if os.path.isdir(pane_dir):
            log.info("removing panes/%s (%s)", pane_id, why)
            try:
                remove_pane(self.bus, pane_dir)
            except OSError as err:
                log.warning("could not remove panes/%s (%s)", pane_id, err)

def _drop_desk_edition(directory):
    """Remove a detail.html left by an older producer (the desk editions are retired)."""
    try:
        os.remove(os.path.join(directory, "detail.html"))
    except FileNotFoundError:
        pass


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
