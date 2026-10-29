"""One producer cycle: the household's standing slots in, link panes out.

A standing slot is a ``link.<pane-id>`` rubric setting (#97, ADR-0018): a web
page the household keeps on the wall. The compositor validates the settings
and publishes them in ``viewport/rubric.json``; this reads them back from
there, so it never parses the signal log itself.

For each slot it keeps a link pane (brasenia ADR-0016) at
``viewport/panes/<pane-id>/``: a ``manifest.json`` with the slot's
``source`` and no ``pane.html``, renewed every cycle. It is a resting pane
(``ambient``), so the remote's Left/Right steps through it and it can be the
default; anything urgent still takes the screen. A slot that is removed takes
its pane with it. A pane another author owns is left alone, so a slot whose id
is taken shows nothing until the other pane goes.

When ``rubric.json`` can't be read, the cycle changes nothing and the panes
leave the bus at their TTL. Contracts v1: every file is written ``x.partial``
then ``x``.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone

PANE_CLASS = "ambient"
TTL_MINUTES = 10
AUTHOR = "links-producer@pub"
ORIGIN = "operator"
DWELL_S = 60
LINK_PREFIX = "link."
PANE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")   # Contracts v1

log = logging.getLogger(__name__)


def write_atomic(path, text):
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(partial, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def slots_from(doc):
    """The slots in a ``rubric.json`` body, pane id -> {"title", "source"}.

    The compositor has validated them already; this only drops an entry
    whose shape it cannot use."""
    eff = doc.get("effective") if isinstance(doc, dict) else None
    if not isinstance(eff, dict):
        return None
    out = {}
    for key, slot in eff.items():
        if not key.startswith(LINK_PREFIX):
            continue
        if not PANE_ID.match(key[len(LINK_PREFIX):]):
            continue   # the compositor checks ids too; this one becomes a path
        if (isinstance(slot, dict) and isinstance(slot.get("title"), str)
                and isinstance(slot.get("source"), dict)
                and isinstance(slot["source"].get("url"), str)):
            out[key[len(LINK_PREFIX):]] = slot
    return out


class Producer:
    def __init__(self, webroot, clock=None):
        viewport = os.path.join(webroot, "viewport")
        self.settings = os.path.join(viewport, "rubric.json")
        self.panes = os.path.join(viewport, "panes")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.unreadable = False
        self.taken = set()   # slot ids whose pane another author owns (logged once)

    def cycle(self):
        slots = slots_from(read_json(self.settings))
        if slots is None:
            if not self.unreadable:
                log.info("cannot read %s; leaving the slot panes to their TTL", self.settings)
                self.unreadable = True
            return
        self.unreadable = False
        now = self.clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        for pane_id, slot in sorted(slots.items()):
            self._keep(pane_id, slot, now)
        self._drop_removed(slots)

    def _owner(self, pane_dir):
        """Who wrote the pane: its manifest's author, or, when a write was cut
        off before the rename, the author in the leftover manifest.json.partial."""
        for name in ("manifest.json", "manifest.json.partial"):
            manifest = read_json(os.path.join(pane_dir, name))
            if isinstance(manifest, dict):
                return manifest.get("author")
        return None

    def _keep(self, pane_id, slot, now):
        pane_dir = os.path.join(self.panes, pane_id)
        if os.path.isdir(pane_dir):
            owner = self._owner(pane_dir)
            if owner not in (AUTHOR, None) or (owner is None and os.listdir(pane_dir)):
                if pane_id not in self.taken:
                    log.info("slot %s: the pane belongs to %s; not replacing it", pane_id, owner)
                    self.taken.add(pane_id)
                return
        self.taken.discard(pane_id)
        os.makedirs(pane_dir, exist_ok=True)
        write_atomic(os.path.join(pane_dir, "manifest.json"), json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": slot["title"],
            "created": now,
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
            "dwell_s": DWELL_S,
            "source": slot["source"],
        }, indent=2, ensure_ascii=False) + "\n")

    def _drop_removed(self, slots):
        try:
            names = os.listdir(self.panes)
        except OSError:
            return
        for name in names:
            pane_dir = os.path.join(self.panes, name)
            if name in slots or not os.path.isdir(pane_dir):
                continue
            if self._owner(pane_dir) == AUTHOR:
                log.info("slot %s removed; taking its pane down", name)
                shutil.rmtree(pane_dir, ignore_errors=True)
