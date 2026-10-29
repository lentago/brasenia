"""A made-up claytonia queue in a temp directory, laid out as the real one is."""

import json
import os
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc)     # 8:40 PM in New York
SECRET = "PROMPT-TEXT-THAT-MUST-NEVER-SHOW"


def stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


class Queue:
    def __init__(self, root):
        self.root = root
        for d in ("inbox", "processing", "done", "failed", "logs", "workers", "scheduled"):
            os.makedirs(os.path.join(root, d), exist_ok=True)

    def write(self, rel, text, age_s=None):
        path = os.path.join(self.root, rel)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if age_s is not None:
            t = (NOW - timedelta(seconds=age_s)).timestamp()
            os.utime(path, (t, t))
        return path

    def worker(self, host, age_s=10):
        self.write("workers/%s.alive" % host, "", age_s)

    def claim(self, runid, owner, project=None, model="opus", started_ago_s=600, origname=None):
        spec = {"prompt": SECRET, "model": model}
        if project:
            spec["project"] = project
        origname = origname or runid.split("-", 1)[1] + ".json"
        if origname.endswith(".json"):
            self.write("processing/" + runid, json.dumps(spec))
        else:
            self.write("processing/" + runid, SECRET)
        self.write("processing/%s.owner" % runid, "owner=%s\nstarted=%d\norigname=%s\n" % (
            owner, int((NOW - timedelta(seconds=started_ago_s)).timestamp()), origname))

    def run(self, label, started_ago_h, duration_s=120, exit_code=0, project="brasenia", model="sonnet",
            limit="", finished=True):
        runid = "%s-%s" % (stamp(NOW - timedelta(hours=started_ago_h)), label)
        end = NOW - timedelta(hours=started_ago_h) + timedelta(seconds=duration_s)
        lines = ["runid=" + runid, "exit=%d" % exit_code, "duration_sec=%d" % duration_s,
                 "project=" + project, "model=" + model, "cost_usd=1.23", "limit=" + limit,
                 "submitter=schedule:test"]
        if finished:
            lines.append("finished=" + end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.write("logs/%s.meta" % runid, "\n".join(lines) + "\n")
        self.write("logs/%s.txt" % runid, SECRET)
        return runid


def pr(repo, number, title, hours_ago, draft=False):
    return {"repo": repo, "number": number, "title": title,
            "created": NOW - timedelta(hours=hours_ago), "draft": draft}
