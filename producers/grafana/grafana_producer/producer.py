"""One producer cycle: render the slots that are due, and write their panes.

Contracts (docs/concept.md, Contracts v1): each slot's pane lives at
``viewport/panes/<pane>/``, a new pane is built in ``staging/`` and renamed in
whole (ADR-0022), an existing one rewritten ``x.partial`` → ``x`` with
``manifest.json`` last, and a pane another author owns is left alone. Each is a
resting pane (``ambient``) beside Home, Weather and Fleet.

Renders are one at a time, each slot every ``refresh_s`` (ADR-0017). A failed
render changes nothing and backs off: the next try waits ``refresh_s``, then
twice that, up to BACKOFF_MAX_S, and never sooner than a 429's
``Retry-After``, which pauses every slot (the limit is the stack's). A pane is renewed only by a good render, and its TTL covers
three refreshes, so one or two failures keep the last image (stamped with its
time) and a dead token or stack takes the pane off the bus.
"""

import errno
import json
import logging
import math
import os
import re
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import render
from .grafana import Client, GrafanaError, urllib_transport

PANE_CLASS = "ambient"
AUTHOR = "grafana-producer@pub"
ORIGIN = "operator"
TTL_MIN_MINUTES = 10
BACKOFF_MAX_S = 3600
DEFAULT_TZ = "America/New_York"

BAD_TOKEN = re.compile(r"[\s\x00-\x1f\x7f-\x9f]")    # whitespace inside, or control characters

log = logging.getLogger(__name__)


def write_atomic(path, data):
    partial = path + ".partial"
    with open(partial, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
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


def ttl_minutes(refresh_s):
    return max(TTL_MIN_MINUTES, math.ceil(3 * refresh_s / 60))


class Producer:
    def __init__(self, webroot, token_file, grafana_url, slots, tz=DEFAULT_TZ,
                 transport=urllib_transport, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.panes_dir = os.path.join(self.bus, "panes")
        self.token_file = token_file
        self.grafana_url = grafana_url
        self.slots = list(slots)
        self.tz = ZoneInfo(tz)
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.next_at = {}         # pane -> when its slot is next due
        self.failures = {}        # pane -> consecutive failed renders
        self.pause_until = None   # a 429's Retry-After: no slot renders before this
        self._no_token = False

    def cycle(self):
        """Render every slot that is due; return how many failed (all due, with no usable token).

        One slot's failure, of any kind, never keeps the others from rendering.
        """
        due = [s for s in self.slots if s.pane not in self.next_at or self.next_at[s.pane] <= self.clock()]
        if not due or self._paused():
            return 0
        token = self._token()
        if token is None:
            return len(due)
        client = Client(self.grafana_url, token, self.transport)
        failed = 0
        for slot in due:
            if self._paused():
                break           # still due; the next cycle after the pause tries it
            if not self._render(client, slot):
                failed += 1
        return failed

    def _paused(self):
        return self.pause_until is not None and self.clock() < self.pause_until

    def _fail(self, slot, now, what, retry_after=None):
        fails = self.failures.get(slot.pane, 0) + 1
        self.failures[slot.pane] = fails
        wait = min(BACKOFF_MAX_S, slot.refresh_s * 2 ** (fails - 1))
        if retry_after is not None:
            wait = max(wait, retry_after)
            self.pause_until = max(self.pause_until or now, now + timedelta(seconds=retry_after))
        self.next_at[slot.pane] = now + timedelta(seconds=wait)
        log.info("grafana %s for %s (%s); trying again in %d s", what, slot.pane, slot.uid, wait)
        return False

    def _render(self, client, slot):
        now = self.clock()
        try:
            png = client.render(slot, now.astimezone(self.tz))
        except GrafanaError as err:
            return self._fail(slot, now, err, err.retry_after)
        except Exception as err:    # the message is not logged: it might carry header values
            return self._fail(slot, now, "failed (%s)" % type(err).__name__)
        try:
            self._write(slot, png, now)
        except Exception as err:    # a full disk, a permission: back off like a failed render
            return self._fail(slot, now, "could not write the pane (%s)" % err)
        self.failures.pop(slot.pane, None)
        self.next_at[slot.pane] = now + timedelta(seconds=slot.refresh_s)
        return True

    def _token(self):
        """The token, read each time a slot is due; None (logged once) while missing or empty."""
        try:
            with open(self.token_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
        if not token:
            if not self._no_token:
                log.warning("no Grafana token at %s; writing nothing until there is one",
                            self.token_file)
                self._no_token = True
            return None
        if BAD_TOKEN.search(token):
            if not self._no_token:      # never the value: it is a credential
                log.warning("the Grafana token at %s has whitespace or control characters in it; "
                            "writing nothing until it is fixed", self.token_file)
                self._no_token = True
            return None
        self._no_token = False
        return token

    def _write(self, slot, png, now):
        pane_dir = os.path.join(self.panes_dir, slot.pane)
        manifest_path = os.path.join(pane_dir, "manifest.json")
        if not self._ours(manifest_path, slot.pane):
            return
        files = [("dashboard.png", png),
                 ("pane.html", render.page(slot, png, now, self.tz)),
                 ("manifest.json", json.dumps({
                     "schema": 1,
                     "class": PANE_CLASS,
                     "title": slot.title,
                     "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "ttl_minutes": ttl_minutes(slot.refresh_s),
                     "author": AUTHOR,
                     "origin": ORIGIN,
                     "dwell_s": slot.dwell_s,
                 }, indent=2, ensure_ascii=False) + "\n")]
        # A new pane appears whole or not at all; when another writer creates
        # it first, the ownership check runs again on the pane that won.
        if not os.path.isdir(pane_dir) and create_pane(self.bus, pane_dir, files):
            return
        if not self._ours(manifest_path, slot.pane):
            return
        for name, data in files:
            write_atomic(os.path.join(pane_dir, name), data)

    def _ours(self, manifest_path, pane_id):
        """True when the pane is absent or this producer's; logs why not otherwise."""
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except FileNotFoundError:
            return True
        except (OSError, ValueError) as err:
            log.warning("panes/%s/manifest.json cannot be read (%s); leaving it alone", pane_id, err)
            return False
        if not isinstance(manifest, dict) or manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", pane_id,
                        manifest.get("author") if isinstance(manifest, dict) else None)
            return False
        return True
