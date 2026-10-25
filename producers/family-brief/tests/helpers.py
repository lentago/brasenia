"""Shared fixtures for the family brief producer tests."""

import copy
import json
import os
from datetime import datetime, timedelta, timezone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name="example"):
    """The parsed ``fixtures/<name>/latest.json`` (made-up family; no real data)."""
    with open(os.path.join(FIXTURES, name, "latest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def with_date(doc, day):
    doc = copy.deepcopy(doc)
    doc["date"] = day
    return doc


class Clock:
    """Starts at 2026-10-25 15:00 UTC, which is 11:00 AM on the fixture's day in New York."""

    def __init__(self, now="2026-10-25T15:00:00Z"):
        self.now = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, hours):
        self.now += timedelta(hours=hours)
