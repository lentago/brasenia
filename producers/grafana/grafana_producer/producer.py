"""One producer cycle: render the slots that are due, and write their panes.

Contracts (docs/concept.md, Contracts v1): each slot's pane lives at
``viewport/panes/<pane>/``, every file is written ``x.partial`` → ``x`` with
``manifest.json`` last, and a pane another author owns is left alone. Each is
a resting pane (``ambient``) beside Home, Weather and Fleet.

Renders are one at a time, each slot every ``refresh_s`` (ADR-0017). A failed
render changes nothing and backs off: the next try waits ``refresh_s``, then
twice that, up to BACKOFF_MAX_S, and never sooner than a 429's
``Retry-After``, which pauses every slot (the limit is the stack's). A pane is renewed only by a good render, and its TTL covers
three refreshes, so one or two failures keep the last image (stamped with its
time) and a dead token or stack takes the pane off the bus.
"""

import json
import logging
import math
import os
import re
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


def ttl_minutes(refresh_s):
    return max(TTL_MIN_MINUTES, math.ceil(3 * refresh_s / 60))


class Producer:
    def __init__(self, webroot, token_file, grafana_url, slots, tz=DEFAULT_TZ,
                 transport=urllib_transport, clock=None):
        self.panes_dir = os.path.join(webroot, "viewport", "panes")
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
        os.makedirs(pane_dir, exist_ok=True)
        write_atomic(os.path.join(pane_dir, "dashboard.png"), png)
        write_atomic(os.path.join(pane_dir, "pane.html"), render.page(slot, png, now, self.tz))
        write_atomic(manifest_path, json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": slot.title,
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": ttl_minutes(slot.refresh_s),
            "author": AUTHOR,
            "origin": ORIGIN,
            "dwell_s": slot.dwell_s,
        }, indent=2, ensure_ascii=False) + "\n")

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
