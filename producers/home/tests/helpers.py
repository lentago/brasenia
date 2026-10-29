"""Shared fixtures for the home producer tests: a made-up house, no real data."""

import json
import os
from datetime import datetime, timedelta, timezone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TOKEN = "test-token-not-real"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def states():
    return load("states.json")


def forecast(kind):
    return load("%s.json" % kind)["service_response"]["weather.home"]["forecast"]


class FakeHA:
    """Answers /api/states and weather.get_forecasts from the fixtures; records every call."""

    def __init__(self, states_doc=None, token=TOKEN):
        self.states = states() if states_doc is None else states_doc
        self.token = token
        self.calls = []
        self.down = False
        self.forecast_status = 200

    def __call__(self, method, url, headers, body=None, timeout=None):
        self.calls.append((method, url, json.loads(body) if body else None))
        if self.down:
            raise OSError("connection refused")
        if headers.get("Authorization") != "Bearer " + self.token:
            return 401, b"401: Unauthorized"
        if method == "GET" and url.endswith("/api/states"):
            return 200, json.dumps(self.states).encode("utf-8")
        if method == "POST" and "/api/services/weather/get_forecasts?return_response" in url:
            if self.forecast_status != 200:
                return self.forecast_status, b"{}"
            kind = json.loads(body)["type"]
            return 200, json.dumps(load("%s.json" % kind)).encode("utf-8")
        return 404, b"{}"

    def forecast_calls(self):
        return [c for c in self.calls if c[0] == "POST"]


class Clock:
    """Starts at 2026-10-29 00:40 UTC: 8:40 PM on 2026-10-28 in New York."""

    def __init__(self, now="2026-10-29T00:40:00Z"):
        self.now = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
