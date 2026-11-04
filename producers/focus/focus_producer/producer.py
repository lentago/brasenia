"""One producer cycle: beacons in, focus panes out.

Contracts (brasenia#26/#27; recorded in docs/concept.md by the compositor
issue): beacons at ``viewport/focus/<host>-<session8>.json``, panes at
``viewport/panes/focus-<owner>-<name>/``. A new pane is built in
``viewport/staging/`` and renamed in whole (ADR-0022); an existing one is
rewritten ``x.partial`` → ``x``, ``manifest.json`` last.
"""

import errno
import json
import logging
import os
import re
import secrets
import shutil
from datetime import datetime, timedelta, timezone

from .github import GitHubError, parse_ts
from .render import GOOD_MAIN, pane_title, render, restamp

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


def _ours(pane_dir):
    """True when the pane's manifest names this producer, or there is none (a
    pane this producer started and never finished). Logs why not otherwise."""
    try:
        with open(os.path.join(pane_dir, "manifest.json"), encoding="utf-8") as fh:
            author = json.load(fh).get("author")
    except FileNotFoundError:
        return True
    except (OSError, ValueError, AttributeError) as err:
        log.warning("panes/%s/manifest.json cannot be read (%s); leaving it alone",
                    os.path.basename(pane_dir), err)
        return False
    if author != AUTHOR:
        log.warning("panes/%s belongs to %r; leaving it alone", os.path.basename(pane_dir), author)
        return False
    return True


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass



def quiet(data, pipeline_row):
    """True when a repo has nothing worth the screen: no open pull requests,
    main's latest run fine (or no push run at all) and no pipeline row. A
    beaconed repo that is quiet gets no pane, so an empty table never
    outranks the resting surface; the pane returns when any of that changes."""
    main = data.get("main")
    return (not data.get("pulls") and not pipeline_row
            and (not main or main.get("conclusion") in GOOD_MAIN))

class Producer:
    def __init__(self, webroot, url_base, github, clock=None, tz=None):
        self.viewport = os.path.join(webroot, "viewport")
        self.focus_dir = os.path.join(self.viewport, "focus")
        self.panes_dir = os.path.join(self.viewport, "panes")
        self.pipeline_url = url_base.rstrip("/") + "/viewport/pipeline.json"
        self.github = github
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.tz = tz

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
                    page = restamp(fh.read(), now, self.tz)
            except FileNotFoundError:
                page = None
            if page is None:
                log.warning("%s: no previous pane to keep; will retry", repo)
                return
        else:
            as_of = datetime.fromtimestamp(fetched, timezone.utc)
            row = next((r for r in pipeline if isinstance(r, dict) and r.get("repo") == repo), None)
            if quiet(data, row):
                self._remove(pane_dir, "quiet: no open pull requests, main fine, nothing in the pipeline")
                return
            page = render(repo, data, row, as_of, now, self.tz)

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
        files = [("pane.html", page),
                 ("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")]
        # A new pane appears whole or not at all. A pane that is already
        # there, or that another writer creates first, is rewritten file by
        # file only when its manifest names this producer (rule 1).
        if not os.path.isdir(pane_dir) and create_pane(self.viewport, pane_dir, files):
            return
        if not _ours(pane_dir):
            return
        for name, text in files:
            write_atomic(os.path.join(pane_dir, name), text)

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

    def _remove(self, pane_dir, why):
        """Remove this producer's pane at ``pane_dir`` (never someone else's)."""
        if not os.path.isdir(pane_dir):
            return
        try:
            with open(os.path.join(pane_dir, "manifest.json"), encoding="utf-8") as fh:
                if json.load(fh).get("author") != AUTHOR:
                    return
        except (OSError, ValueError, AttributeError):
            pass  # no manifest yet: a pane this producer started and never finished
        log.info("removing pane %s (%s)", os.path.basename(pane_dir), why)
        try:
            remove_pane(self.viewport, pane_dir)
        except OSError as err:
            log.warning("could not remove pane %s (%s)", os.path.basename(pane_dir), err)

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
            try:
                remove_pane(self.viewport, path)
            except OSError as err:
                log.warning("could not remove pane %s (%s)", name, err)
            if repo:
                self.github.forget(repo)
