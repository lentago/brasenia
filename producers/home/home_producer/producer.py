"""One producer cycle: Home Assistant's states in, the home and weather panes out.

Contracts (docs/concept.md, Contracts v1): the panes live at
``viewport/panes/home/`` and ``viewport/panes/weather/``, a new pane is built
in ``staging/`` and renamed in whole (ADR-0022), an existing one rewritten
``x.partial`` → ``x`` with ``manifest.json`` last, and a pane another author
owns is left alone. Both are resting panes (``ambient``) the household can make
the default from the Roku remote (#83, #86).

When Home Assistant can't be read (no token yet, a rejected token, the
network), the cycle changes nothing and the panes leave the bus at their TTL,
so the wall never shows the house as it was a while ago. Forecasts change
slowly, so they are fetched every FORECAST_S and the last good ones are kept
for up to FORECAST_KEEP_S through a failed fetch.
"""

import errno
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import home, weather
from .ha import Client, HAError, urllib_transport

HOME_ID, WEATHER_ID = "home", "weather"
PANE_CLASS = "ambient"
TTL_MINUTES = 10
AUTHOR = "home-producer@pub"
ORIGIN = "operator"
DWELL_S = 60
FORECAST_S = 600
FORECAST_KEEP_S = 3 * 3600
DEFAULT_URL = "http://homeassistant.lan:8123"
DEFAULT_TZ = "America/New_York"

log = logging.getLogger(__name__)

# Returned by _read_manifest when a pane directory holds a manifest this
# producer cannot read or parse; the cycle then leaves that pane alone.
UNKNOWN = object()


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
    def __init__(self, webroot, token_file, ha_url=DEFAULT_URL, weather_entity=None, hide=(),
                 tz=DEFAULT_TZ, transport=urllib_transport, clock=None):
        self.bus = os.path.join(webroot, "viewport")
        self.panes_dir = os.path.join(self.bus, "panes")
        self.token_file = token_file
        self.ha_url = ha_url
        self.weather_entity = weather_entity
        self.hide = frozenset(hide)
        self.tz = ZoneInfo(tz)
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.forecasts = {}       # kind -> (fetched at, entity id, entries)
        self._no_token = False

    def cycle(self):
        now = self.clock()
        token = self._token()
        if token is None:
            return
        client = Client(self.ha_url, token, self.transport)
        try:
            states = client.states()
        except HAError as err:
            log.info("home assistant %s; leaving the panes to their TTL", err)
            return
        self._write(HOME_ID, home.TITLE, home.render_home(home.summarize(states, self.hide), now, self.tz), now)
        entity = weather.pick(states, self.weather_entity)
        if entity is None:
            log.info("no %s; no weather pane", self.weather_entity or "weather entity")
            self._remove(WEATHER_ID)
            return
        hourly = self._forecast(client, entity["entity_id"], "hourly", now)
        daily = self._forecast(client, entity["entity_id"], "daily", now)
        self._write(WEATHER_ID, weather.TITLE, weather.render_weather(entity, hourly, daily, now, self.tz), now)

    def _token(self):
        """The token, read each cycle; None (logged once) while it is missing or empty."""
        try:
            with open(self.token_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
        if not token:
            if not self._no_token:
                log.warning("no Home Assistant token at %s; writing nothing until there is one",
                            self.token_file)
                self._no_token = True
            return None
        self._no_token = False
        return token

    def _forecast(self, client, entity_id, kind, now):
        """The ``kind`` forecast, refetched every FORECAST_S; the last good one through failures."""
        held = self.forecasts.get(kind)
        if held and held[1] == entity_id and (now - held[0]).total_seconds() < FORECAST_S:
            return held[2]
        try:
            entries = client.forecast(entity_id, kind)
        except HAError as err:
            if held and held[1] == entity_id and (now - held[0]).total_seconds() < FORECAST_KEEP_S:
                log.info("%s forecast %s; keeping the one from %s", kind, err, held[0].isoformat())
                return held[2]
            log.info("%s forecast %s; none on the pane", kind, err)
            return None
        self.forecasts[kind] = (now, entity_id, entries)
        return entries

    def _write(self, pane_id, title, page, now):
        pane_dir = os.path.join(self.panes_dir, pane_id)
        manifest_path = os.path.join(pane_dir, "manifest.json")
        if not self._ours(manifest_path, pane_id):
            return
        files = [("pane.html", page),
                 ("manifest.json", json.dumps({
                     "schema": 1,
                     "class": PANE_CLASS,
                     "title": title,
                     "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "ttl_minutes": TTL_MINUTES,
                     "author": AUTHOR,
                     "origin": ORIGIN,
                     "dwell_s": DWELL_S,
                 }, indent=2, ensure_ascii=False) + "\n")]
        # A new pane appears whole or not at all; when another writer creates
        # it first, the ownership check runs again on the pane that won.
        if not os.path.isdir(pane_dir) and create_pane(self.bus, pane_dir, files):
            return
        if not self._ours(manifest_path, pane_id):
            return
        for name, text in files:
            write_atomic(os.path.join(pane_dir, name), text)

    def _remove(self, pane_id):
        pane_dir = os.path.join(self.panes_dir, pane_id)
        if os.path.isdir(pane_dir) and self._ours(os.path.join(pane_dir, "manifest.json"), pane_id):
            log.info("removing panes/%s", pane_id)
            try:
                remove_pane(self.bus, pane_dir)
            except OSError as err:
                log.warning("could not remove panes/%s (%s)", pane_id, err)

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
