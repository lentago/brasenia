"""Shared fixtures for the grafana producer tests: made-up slots and PNGs, no network."""

import os
import struct
import urllib.parse
import zlib
from datetime import datetime, timedelta, timezone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SLOTS = os.path.join(FIXTURES, "slots.json")
TOKEN = "test-token-not-real"
STACK = "https://grafana.test"


def make_png(width, height):
    """A valid, all-black ``width``×``height`` greyscale PNG."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeGrafana:
    """Answers /render/d/<uid> with a PNG of the asked-for size; records every call."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.calls = []
        self.down = False
        self.status = 200
        self.headers = {}
        self.body = None

    def __call__(self, url, headers, timeout=None):
        self.calls.append(url)
        if self.down:
            raise OSError("connection refused")
        if headers.get("Authorization") != "Bearer " + self.token:
            return 302, {"Location": STACK + "/login"}, b""
        if self.status != 200:
            return self.status, self.headers, b"{}"
        if self.body is not None:
            return 200, {"Content-Type": "text/html"}, self.body
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        scale = int(query["scale"])
        return 200, {"Content-Type": "image/png"}, make_png(
            int(query["width"]) * scale, int(query["height"]) * scale)

    def query(self, i=-1):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.calls[i]).query))


class Clock:
    """Starts at 2026-10-29 00:40 UTC: 8:40 PM on 2026-10-28 in New York."""

    def __init__(self, now="2026-10-29T00:40:00Z"):
        self.now = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
