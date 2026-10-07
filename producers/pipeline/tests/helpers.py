"""Shared fixtures for the pipeline producer tests."""

import copy
import json
import os
from datetime import datetime, timedelta, timezone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    """The parsed ``fixtures/<name>/viewport/pipeline.json`` (``example`` is drosera#266's verbatim)."""
    with open(os.path.join(FIXTURES, name, "viewport", "pipeline.json"), encoding="utf-8") as fh:
        return json.load(fh)


def landed(doc, repo):
    """``doc`` with ``repo``'s change landed: live green on head, no longer in flight."""
    doc = copy.deepcopy(doc)
    for row in doc["repos"]:
        if row["repo"] == repo:
            row.update(in_flight=False, in_flight_since=None, stuck=False)
            row["stages"][-1].update(state=3, sha=row["head"]["sha"], detail="landed")
    return doc


class Clock:
    def __init__(self, now="2026-10-07T22:11:00Z"):
        self.now = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += timedelta(minutes=minutes)
