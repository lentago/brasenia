"""One producer cycle: beacons in, focus panes out.

Contracts (brasenia#26/#27; recorded in docs/concept.md by the compositor
issue): beacons at ``viewport/focus/<host>-<session8>.json``, panes at
``viewport/panes/focus-<owner>-<name>/``, every file written
``x.partial`` → ``x`` and ``manifest.json`` last.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone

from .github import GitHubError, parse_ts
from .render import pane_title, render, restamp

STALE_AFTER = timedelta(minutes=10)
TTL_MINUTES = 10
AUTHOR = "focus-producer@pub"
PREFIX = "focus-"
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")

log = logging.getLogger(__name__)


def pane_id(repo):
    """``lentago/.github`` → ``focus-lentago--github``."""
    return PREFIX + re.sub(r"[^a-z0-9]", "-", repo.lower())


def read_beacons(focus_dir, now):
    """Return ``{repo: origin}`` from fresh beacons; delete stale or unparseable ones.

    ``origin`` is ``operator`` when any fresh beacon for the repo is
    ``operator``, else ``fleet``. Beacons with a null (or malformed) repo
    are fresh but produce no pane.
    """
    repos = {}
    try:
        names = sorted(os.listdir(focus_dir))
    except FileNotFoundError:
        return repos
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(focus_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                beacon = json.load(fh)
            ts = parse_ts(beacon["ts"])
        except FileNotFoundError:
            continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
            log.info("deleting unparseable beacon %s (%s)", name, err)
            _unlink(path)
            continue
        if now - ts > STALE_AFTER:
            log.info("deleting stale beacon %s (ts %s)", name, beacon["ts"])
            _unlink(path)
            continue
        repo = beacon.get("repo")
        if not isinstance(repo, str) or not REPO_RE.match(repo):
            continue
        if beacon.get("origin") == "operator" or repos.get(repo) == "operator":
            repos[repo] = "operator"
        else:
            repos[repo] = "fleet"
    return repos


def write_atomic(path, text):
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(partial, path)


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class Producer:
    def __init__(self, webroot, url_base, github, clock=None):
        self.viewport = os.path.join(webroot, "viewport")
        self.focus_dir = os.path.join(self.viewport, "focus")
        self.panes_dir = os.path.join(self.viewport, "panes")
        self.pipeline_url = url_base.rstrip("/") + "/viewport/pipeline.json"
        self.github = github
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def cycle(self):
        now = self.clock()
        repos = read_beacons(self.focus_dir, now)
        pipeline = self._pipeline() if repos else []
        for repo, origin in sorted(repos.items()):
            try:
                self._render_repo(repo, origin, pipeline, now, len(repos))
            except OSError as err:
                log.error("%s: could not write pane: %s", repo, err)
            except Exception:  # an odd API payload must not stall other repos or cleanup
                log.exception("%s: render failed", repo)
        self._cleanup({pane_id(r) for r in repos})

    def _render_repo(self, repo, origin, pipeline, now, active):
        pane_dir = os.path.join(self.panes_dir, pane_id(repo))
        page_path = os.path.join(pane_dir, "pane.html")
        try:
            data, fetched = self.github.repo(repo, active)
        except GitHubError as err:
            log.warning("%s: GitHub refresh failed, keeping previous pane: %s", repo, err)
            try:
                with open(page_path, encoding="utf-8") as fh:
                    page = restamp(fh.read(), now)
            except FileNotFoundError:
                page = None
            if page is None:
                log.warning("%s: no previous pane to keep; will retry", repo)
                return
        else:
            as_of = datetime.fromtimestamp(fetched, timezone.utc)
            row = next((r for r in pipeline if isinstance(r, dict) and r.get("repo") == repo), None)
            page = render(repo, data, row, as_of, now)

        os.makedirs(pane_dir, exist_ok=True)
        write_atomic(page_path, page)
        manifest = {
            "schema": 1,
            "class": "focus",
            "title": pane_title(repo),
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": origin,
            "repo": repo,
        }
        write_atomic(os.path.join(pane_dir, "manifest.json"),
                     json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    def _pipeline(self):
        """This cycle's pipeline.json rows; any failure means no rows."""
        try:
            status, _headers, body = self.github.transport(self.pipeline_url, {})
            if status != 200:
                return []
            rows = json.loads(body)
        except (OSError, ValueError) as err:
            log.info("pipeline.json unreadable: %s", err)
            return []
        return rows if isinstance(rows, list) else []

    def _cleanup(self, live):
        """Remove focus-* pane dirs with no fresh beacon. Other dirs are never touched."""
        try:
            names = os.listdir(self.panes_dir)
        except FileNotFoundError:
            return
        for name in names:
            path = os.path.join(self.panes_dir, name)
            if not name.startswith(PREFIX) or name in live or not os.path.isdir(path):
                continue
            repo = None
            try:
                with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
                    manifest = json.load(fh)
                if manifest.get("author") != AUTHOR:
                    continue  # someone else's focus-* claim
                repo = manifest.get("repo")
            except (OSError, ValueError, AttributeError):
                pass  # no manifest yet: a pane this producer started and never finished
            log.info("removing pane %s (no fresh beacon)", name)
            shutil.rmtree(path, ignore_errors=True)
            if repo:
                self.github.forget(repo)
