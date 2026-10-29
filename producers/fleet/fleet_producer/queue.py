"""Read the claytonia job queue the way its own tools do, without writing to it.

The layout and rules are claytonia's (``bin/cr-submit``'s occupancy probe,
``process-inbox``):

* ``workers/<host>.alive``: a heartbeat touched every 30 s; a worker is alive
  while it is at most HEARTBEAT_STALE (90 s) old.
* ``processing/<runid>`` plus ``processing/<runid>.owner`` (``owner=``,
  ``started=``, ``origname=``): a claimed job. It counts as busy only while
  its owner is alive; a dead owner's claim is the reaper's to requeue.
* ``inbox/<name>``: waiting, skipping ``.*``, ``*.partial``, ``*.tmp``,
  ``*.swp`` and ``*.owner`` (what process-inbox never claims).
* ``logs/<runid>.meta``: ``key=value`` lines written when a run ends
  (``exit``, ``duration_sec``, ``project``, ``model``, ``limit``,
  ``finished``). A runid starts with its UTC start time
  (``20261028T233032Z-...``), so only recent names are opened.

Of a JSON spec only ``project`` and ``model`` are kept; a text job's file is
never opened. Nothing here reads a prompt, a log or a transcript.
"""

import json
import os
from datetime import datetime, timedelta, timezone

HEARTBEAT_STALE = 90            # seconds, claytonia's CLAUDE_HEARTBEAT_STALE default
RETIRED_AFTER = 24 * 3600       # a heartbeat older than this is a retired worker, not a dead one
RUN_WINDOW = timedelta(hours=24)
SPEC_MAX_BYTES = 1 << 20


def snapshot(jobs, now, cache=None):
    """The queue at ``now``: workers, the waiting jobs, and the last day's runs.

    ``cache`` (a dict the caller keeps) holds parsed ``.meta`` files, which
    never change once a run has finished.
    """
    alive, stale = _heartbeats(jobs, now)
    claims = _claims(jobs, alive)
    workers = []
    for host in sorted(alive):
        claim = claims.get(host)
        workers.append({"name": host, "state": "busy" if claim else "idle",
                        "project": claim["project"] if claim else None,
                        "model": claim["model"] if claim else None,
                        "since": claim["started"] if claim else None})
    for host, seen in sorted(stale.items()):
        workers.append({"name": host, "state": "silent", "project": None, "model": None, "since": seen})
    waiting = _waiting(jobs)
    return {"workers": workers, "alive": len(alive), "busy": len(claims),
            "waiting": len(waiting), "waiting_projects": sorted({p for p in waiting if p}),
            "runs": _runs(jobs, now, cache if cache is not None else {})}


def _heartbeats(jobs, now):
    alive, stale = set(), {}
    for entry in _scan(os.path.join(jobs, "workers")):
        if not entry.name.endswith(".alive"):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        host = entry.name[:-len(".alive")]
        age = now.timestamp() - mtime
        if age <= HEARTBEAT_STALE:
            alive.add(host)
        elif age <= RETIRED_AFTER:
            stale[host] = datetime.fromtimestamp(mtime, timezone.utc)
    return alive, stale


def _claims(jobs, alive):
    """``{owner: {"project", "model", "started"}}`` for claims held by a live worker."""
    processing = os.path.join(jobs, "processing")
    claims = {}
    for entry in _scan(processing):
        if not entry.name.endswith(".owner"):
            continue
        runid = entry.name[:-len(".owner")]
        if not os.path.isfile(os.path.join(processing, runid)):
            continue                      # a stray owner; the job has been filed
        owner = _keyvalues(entry.path)
        host = owner.get("owner")
        if not host or host not in alive:
            continue
        spec = {}
        if owner.get("origname", "").endswith(".json") or not owner.get("origname"):
            spec = _spec(os.path.join(processing, runid))
        try:
            started = datetime.fromtimestamp(int(owner.get("started", "")), timezone.utc)
        except (ValueError, OverflowError, OSError):
            started = None
        claims[host] = {"project": _text(spec.get("project")), "model": _text(spec.get("model")),
                        "started": started}
    return claims


def _waiting(jobs):
    """The project of each job waiting in the inbox (None for a text job or no project)."""
    projects = []
    for entry in _scan(os.path.join(jobs, "inbox")):
        name = entry.name
        if name.startswith(".") or name.endswith((".partial", ".tmp", ".swp", ".owner")):
            continue
        if not entry.is_file():
            continue
        projects.append(_text(_spec(entry.path).get("project")) if name.endswith(".json") else None)
    return projects


def _runs(jobs, now, cache):
    """Runs that finished in the last 24 hours, newest first."""
    logs = os.path.join(jobs, "logs")
    earliest = now - RUN_WINDOW - timedelta(hours=2)   # started before the window, finished in it
    runs = []
    for entry in _scan(logs):
        if not entry.name.endswith(".meta"):
            continue
        started = _runid_time(entry.name)
        if started is None or started < earliest:
            continue
        meta = cache.get(entry.name)
        if meta is None:
            meta = _keyvalues(entry.path)
            if "finished" in meta:        # complete: it never changes again
                cache[entry.name] = meta
        finished = _time(meta.get("finished"))
        if finished is None or not now - RUN_WINDOW <= finished <= now + timedelta(minutes=5):
            continue
        try:
            code = int(meta.get("exit", ""))
        except ValueError:
            code = None
        try:
            duration = int(float(meta.get("duration_sec", "")))
        except ValueError:
            duration = None
        runs.append({"finished": finished, "project": _text(meta.get("project")),
                     "model": _text(meta.get("model")), "exit": code,
                     "limit": _text(meta.get("limit")), "duration": duration})
    runs.sort(key=lambda r: r["finished"], reverse=True)
    return runs


def _scan(path):
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


def _keyvalues(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read(64 * 1024).splitlines()
    except OSError:
        return {}
    out = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _spec(path):
    """A JSON spec's ``project`` and ``model``, never anything else in it."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.loads(fh.read(SPEC_MAX_BYTES))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {k: doc.get(k) for k in ("project", "model")}


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() not in ("", "-") else None


def _runid_time(name):
    try:
        return datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _time(value):
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
