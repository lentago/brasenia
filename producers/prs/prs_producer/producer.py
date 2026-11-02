"""One producer cycle: GitHub search in, the PRs pane out.

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/prs/``, every file is written ``x.partial`` → ``x`` with
``manifest.json`` last, and a pane another author owns is left alone. It is a
resting pane (``ambient``) the household can make the default from the Roku
remote (#83, #86).

The search runs every REFRESH_S. A failed refresh keeps the last good data,
and the pane says how old it is. Once the last good data is older than
STALE_S, the cycle stops renewing the pane, so it leaves the bus at its TTL
rather than showing an old list (ADR-0014's rule for resting panes).
"""

import json
import logging
import os
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


class Producer:
    def __init__(self, webroot, tz=DEFAULT_TZ, scope=github.DEFAULT_SCOPE,
                 snapshot=github.snapshot, clock=None):
        self.pane_dir = os.path.join(webroot, "viewport", "panes", PANE_ID)
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
        os.makedirs(self.pane_dir, exist_ok=True)
        status = {"as_of": self.as_of, "error": self.error, "tried": self.tried}
        write_atomic(os.path.join(self.pane_dir, "pane.html"),
                     render(self.data, status, self.scope, now, self.tz))
        write_atomic(os.path.join(self.pane_dir, "manifest.json"), json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": TITLE,
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
            "dwell_s": DWELL_S,
        }, indent=2, ensure_ascii=False) + "\n")

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
