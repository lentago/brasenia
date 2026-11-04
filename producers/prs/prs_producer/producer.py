"""One producer cycle: GitHub search in, the PRs pane out.

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/prs/``, a new pane is built in ``staging/`` and renamed in
whole (ADR-0022), an existing one rewritten ``x.partial`` → ``x`` with
``manifest.json`` last, and a pane another author owns is left alone. It is a
resting pane (``ambient``) the household can make the default from the Roku
remote (#83, #86).

The search runs every REFRESH_S. A failed refresh keeps the last good data,
and the pane says how old it is. Once the last good data is older than
STALE_S, the cycle stops renewing the pane, so it leaves the bus at its TTL
rather than showing an old list (ADR-0014's rule for resting panes).
"""

import errno
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import github
from .render import render

PANE_ID = "prs"
PANE_CLASS = "ambient"
TITLE = "Pull requests"
TTL_MINUTES = 10
AUTHOR = "prs-producer@pub"
ORIGIN = "operator"
DWELL_S = 60
REFRESH_S = 120
STALE_S = 900
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


class Producer:
    def __init__(self, webroot, tz=DEFAULT_TZ, scope=github.DEFAULT_SCOPE,
                 snapshot=github.snapshot, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.pane_dir = os.path.join(self.bus, "panes", PANE_ID)
        self.tz = ZoneInfo(tz)
        self.scope = scope
        self.snapshot = snapshot
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.data = None          # the last good snapshot
        self.as_of = None         # when it was fetched
        self.error = None         # the last refresh's failure, or None
        self.tried = None         # when the last refresh ran

    def cycle(self):
        now = self.clock()
        self._refresh(now)
        if self.data is None:
            log.info("no PR data yet (%s); nothing to write", self.error or "not fetched")
            return
        if (now - self.as_of).total_seconds() > STALE_S:
            log.info("PR data is from %s; leaving the pane to its TTL", self.as_of.isoformat())
            return
        if not self._ours():
            return
        status = {"as_of": self.as_of, "error": self.error, "tried": self.tried}
        files = [("pane.html", render(self.data, status, self.scope, now, self.tz)),
                 ("manifest.json", json.dumps({
                     "schema": 1,
                     "class": PANE_CLASS,
                     "title": TITLE,
                     "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "ttl_minutes": TTL_MINUTES,
                     "author": AUTHOR,
                     "origin": ORIGIN,
                     "dwell_s": DWELL_S,
                 }, indent=2, ensure_ascii=False) + "\n")]
        # A new pane appears whole or not at all; when another writer creates
        # it first, the ownership check runs again on the pane that won.
        if not os.path.isdir(self.pane_dir) and create_pane(self.bus, self.pane_dir, files):
            return
        if not self._ours():
            return
        for name, text in files:
            write_atomic(os.path.join(self.pane_dir, name), text)

    def _refresh(self, now):
        if self.tried is not None and (now - self.tried).total_seconds() < REFRESH_S:
            return
        self.tried = now
        midnight = now.astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            data = self.snapshot(midnight, self.scope)
        except github.GitHubError as err:
            log.info("GitHub search: %s; keeping the last list", err)
            self.error = str(err)
            return
        self.data, self.as_of, self.error = data, now, None

    def _ours(self):
        """True when the pane is absent or this producer's; logs why not otherwise."""
        try:
            with open(os.path.join(self.pane_dir, "manifest.json"), encoding="utf-8") as fh:
                manifest = json.load(fh)
        except FileNotFoundError:
            return True
        except (OSError, ValueError) as err:
            log.warning("panes/%s/manifest.json cannot be read (%s); leaving it alone", PANE_ID, err)
            return False
        if not isinstance(manifest, dict) or manifest.get("author") != AUTHOR:
            log.warning("panes/%s belongs to %r; leaving it alone", PANE_ID,
                        manifest.get("author") if isinstance(manifest, dict) else None)
            return False
        return True
