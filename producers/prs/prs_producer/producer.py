"""One producer cycle: GitHub in, the PRs pane out.

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

With pub's GitHub token, each good refresh also reads the state of the open
rows on the pane (checks, auto-merge, review; #137) in one GraphQL query,
inside ADR-0021's budget: at most STATE_BUDGET points an hour, and none while
GitHub reports fewer than LOW_REMAINING left in the window. A state older than
STALE_S is dropped, and its row shows the author again.
"""

import errno
import json
import logging
import os
import secrets
import shutil
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import github
from .render import ROWS, render

PANE_ID = "prs"
PANE_CLASS = "ambient"
TITLE = "Pull requests"
TTL_MINUTES = 10
AUTHOR = "prs-producer@pub"
ORIGIN = "operator"
DWELL_S = 60
REFRESH_S = 120
STALE_S = 900
STATE_BUDGET = 200      # GraphQL points an hour, the PRs pane's share (ADR-0021)
LOW_REMAINING = 1000    # no state query while GitHub reports fewer left (ADR-0021)
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
                 client=None, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.pane_dir = os.path.join(self.bus, "panes", PANE_ID)
        self.tz = ZoneInfo(tz)
        self.scope = scope
        self.client = client or github.Client()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.data = None          # the last good snapshot
        self.as_of = None         # when it was fetched
        self.error = None         # the last refresh's failure, or None
        self.tried = None         # when the last refresh ran
        self.states = {}          # node id -> (state, when it was read)
        self.spent = deque()      # (when, cost) of each state query in the last hour
        self.paused_until = None  # no state query before this (GitHub's budget ran low)

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
        status = {"as_of": self.as_of, "error": self.error, "tried": self.tried,
                  "token": self.client.authenticated,
                  "paused": self.paused_until is not None and now < self.paused_until,
                  "states": {pid: state for pid, (state, at) in self.states.items()
                             if (now - at).total_seconds() <= STALE_S}}
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
            data = self.client.snapshot(midnight, self.scope)
        except github.GitHubError as err:
            log.info("GitHub search: %s; keeping the last list", err)
            self.error = str(err)
            return
        self.data, self.as_of, self.error = data, now, None
        self._refresh_states(now)

    def _refresh_states(self, now):
        """Read the state of the open rows on the pane, inside ADR-0021's budget."""
        shown = [e["id"] for e in self.data["events"][:ROWS] if e["status"] == "open" and e.get("id")]
        self.states = {pid: held for pid, held in self.states.items() if pid in shown}
        if not self.client.authenticated:
            self.states = {}
            return
        if not shown:
            return
        if self.paused_until is not None:
            if now < self.paused_until:
                return
            self.paused_until = None
        while self.spent and (now - self.spent[0][0]).total_seconds() >= 3600:
            self.spent.popleft()
        if sum(cost for _, cost in self.spent) >= STATE_BUDGET:
            log.info("PR state has spent its %d GraphQL points this hour; keeping the last",
                     STATE_BUDGET)
            return
        try:
            states, rate = self.client.states(shown)
        except github.GitHubError as err:
            log.info("PR state: %s; keeping the last", err)
            return
        if rate is None:              # the token was refused: back to the token-less view
            self.states = {}
            return
        self.spent.append((now, rate["cost"]))
        self.states.update((pid, (state, now)) for pid, state in states.items())
        if rate["remaining"] is not None and rate["remaining"] < LOW_REMAINING:
            self.paused_until = rate["reset"] if rate["reset"] and rate["reset"] > now \
                else now + timedelta(hours=1)
            log.warning("GitHub's GraphQL budget is down to %d; no PR state until %s",
                        rate["remaining"], self.paused_until.isoformat())

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
