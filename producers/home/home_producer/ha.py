"""A small Home Assistant REST client: all states, and a weather entity's forecasts.

The token is sent as a bearer header and never logged or rendered. Home
Assistant has no read-only role, so the producer keeps to two read calls:
``GET /api/states`` and ``weather.get_forecasts``, a service that only
answers (``?return_response``) and changes nothing.
"""

import json
import urllib.error
import urllib.request

TIMEOUT_S = 15


class HAError(Exception):
    """Any Home Assistant failure: network, HTTP status, or an unexpected body."""


def urllib_transport(method, url, headers, body=None, timeout=TIMEOUT_S):
    """Send one request; return ``(status, body bytes)``. Raises OSError on network failure."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


class Client:
    def __init__(self, base_url, token, transport=urllib_transport):
        self.base = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def states(self):
        """Every entity's state, as Home Assistant's list of state objects."""
        doc = self._call("GET", "/api/states")
        if not isinstance(doc, list):
            raise HAError("/api/states is not a list")
        return [s for s in doc if isinstance(s, dict) and isinstance(s.get("entity_id"), str)]

    def forecast(self, entity_id, kind):
        """``weather.get_forecasts`` for one entity: its list of ``kind`` ("hourly", "daily") entries."""
        doc = self._call("POST", "/api/services/weather/get_forecasts?return_response",
                         {"entity_id": entity_id, "type": kind})
        try:
            forecast = doc["service_response"][entity_id]["forecast"]
        except (KeyError, TypeError):
            raise HAError("no %s forecast for %s" % (kind, entity_id)) from None
        if not isinstance(forecast, list):
            raise HAError("the %s forecast for %s is not a list" % (kind, entity_id))
        return [f for f in forecast if isinstance(f, dict)]

    def _call(self, method, path, payload=None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json",
                   "User-Agent": "brasenia-home-producer"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        try:
            status, raw = self.transport(method, self.base + path, headers, body)
        except OSError as err:
            raise HAError("unreachable (%s)" % err) from None
        if status == 401:
            raise HAError("rejected the token (HTTP 401)")
        if status != 200:
            raise HAError("answered %s with HTTP %s" % (path.split("?")[0], status))
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HAError("%s is not JSON" % path.split("?")[0]) from None
