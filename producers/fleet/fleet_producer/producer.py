"""One producer cycle: the job queue and GitHub in, the fleet pane out.

Contracts (docs/concept.md, Contracts v1): the pane lives at
``viewport/panes/fleet/``, every file is written ``x.partial`` → ``x`` with
``manifest.json`` last, and a pane another author owns is left alone. It is a
resting pane (``ambient``) the household can make the default from the Roku
remote (#83, #86).

When the queue can't be read (the mount is missing), the cycle changes
nothing and the pane leaves the bus at its TTL. The agent-PR search runs
every PR_S; a failed search keeps the last good list, marked with its time.
"""

import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import github, queue
from .render import render

PANE_ID = "fleet"
PANE_CLASS = "ambient"
TITLE = "Fleet"
TTL_MINUTES = 10
AUTHOR = "fleet-producer@pub"
ORIGIN = "operator"
DWELL_S = 60
PR_S = 300
DEFAULT_JOBS = "/srv/claude-jobs"
DEFAULT_TZ = "America/New_York"

log = logging.getLogger(__name__)


def write_atomic(path, text):
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(partial, path)


class Producer:
    def __init__(self, webroot, jobs=DEFAULT_JOBS, tz=DEFAULT_TZ, search=github.agent_prs, clock=None):
        self.pane_dir = os.path.join(webroot, "viewport", "panes", PANE_ID)
        self.jobs = jobs
        self.tz = ZoneInfo(tz)
        self.search = search
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.meta_cache = {}
        self.prs = None           # {"total", "items", "as_of", "error"}
        self.searched = None

    def cycle(self):
        now = self.clock()
        if not os.path.isdir(os.path.join(self.jobs, "workers")):
            log.info("no job queue at %s (is the mount there?); leaving the pane to its TTL", self.jobs)
            return
        snap = queue.snapshot(self.jobs, now, self.meta_cache)
        self._search(now)
        if not self._ours():
            return
        os.makedirs(self.pane_dir, exist_ok=True)
        write_atomic(os.path.join(self.pane_dir, "pane.html"), render(snap, self.prs, now, self.tz))
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

    def _search(self, now):
        if self.searched is not None and (now - self.searched).total_seconds() < PR_S:
            return
        self.searched = now
        try:
            total, items = self.search()
        except github.GitHubError as err:
            log.info("agent PRs: %s; keeping the last list", err)
            if self.prs is None:
                self.prs = {"total": 0, "items": [], "as_of": None, "error": str(err)}
            else:
                self.prs["error"] = str(err)
            return
        self.prs = {"total": total, "items": items, "as_of": now, "error": None}

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
