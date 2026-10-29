"""One producer cycle: Home Assistant's states in, the home and weather panes out.

Contracts (docs/concept.md, Contracts v1): the panes live at
``viewport/panes/home/`` and ``viewport/panes/weather/``, every file is
written ``x.partial`` → ``x`` with ``manifest.json`` last, and a pane another
author owns is left alone. Both are resting panes (``ambient``) the household
can make the default from the Roku remote (#83, #86).

When Home Assistant can't be read (no token yet, a rejected token, the
network), the cycle changes nothing and the panes leave the bus at their TTL,
so the wall never shows the house as it was a while ago. Forecasts change
slowly, so they are fetched every FORECAST_S and the last good ones are kept
for up to FORECAST_KEEP_S through a failed fetch.
"""

import json
import logging
import os
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


class Producer:
    def __init__(self, webroot, token_file, ha_url=DEFAULT_URL, weather_entity=None, hide=(),
                 tz=DEFAULT_TZ, transport=urllib_transport, clock=None):
        self.panes_dir = os.path.join(webroot, "viewport", "panes")
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
        os.makedirs(pane_dir, exist_ok=True)
        write_atomic(os.path.join(pane_dir, "pane.html"), page)
        write_atomic(manifest_path, json.dumps({
            "schema": 1,
            "class": PANE_CLASS,
            "title": title,
            "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_minutes": TTL_MINUTES,
            "author": AUTHOR,
            "origin": ORIGIN,
            "dwell_s": DWELL_S,
        }, indent=2, ensure_ascii=False) + "\n")

    def _remove(self, pane_id):
        pane_dir = os.path.join(self.panes_dir, pane_id)
        if os.path.isdir(pane_dir) and self._ours(os.path.join(pane_dir, "manifest.json"), pane_id):
            log.info("removing panes/%s", pane_id)
            shutil.rmtree(pane_dir, ignore_errors=True)

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
