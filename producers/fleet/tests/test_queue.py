import shutil
import tempfile
import unittest

from helpers import NOW, SECRET, Queue

from fleet_producer import queue


class QueueTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.q = Queue(self.root)

    def snap(self, cache=None):
        return queue.snapshot(self.root, NOW, cache)

    def test_workers_alive_silent_and_retired(self):
        self.q.worker("runner-a", age_s=20)
        self.q.worker("runner-b", age_s=90)          # exactly the stale limit: still alive
        self.q.worker("runner-c", age_s=600)         # stopped ten minutes ago
        self.q.worker("runner-old", age_s=3 * 86400) # retired
        snap = self.snap()
        self.assertEqual(snap["alive"], 2)
        self.assertEqual([(w["name"], w["state"]) for w in snap["workers"]],
                         [("runner-a", "idle"), ("runner-b", "idle"), ("runner-c", "silent")])

    def test_a_claim_held_by_a_live_worker_is_busy(self):
        self.q.worker("runner-a")
        self.q.worker("runner-b")
        self.q.claim("20261029T003000Z-fix-thing", "runner-a", project="kalmia", model="opus", started_ago_s=720)
        snap = self.snap()
        self.assertEqual(snap["busy"], 1)
        busy = snap["workers"][0]
        self.assertEqual((busy["state"], busy["project"], busy["model"]), ("busy", "kalmia", "opus"))
        self.assertEqual((NOW - busy["since"]).total_seconds(), 720)

    def test_dead_owners_and_stray_claims_are_not_busy(self):
        self.q.worker("runner-a")
        self.q.claim("20261029T003000Z-orphan", "runner-dead", project="kalmia")
        self.q.write("processing/20261029T003100Z-filed.owner", "owner=runner-a\nstarted=1\n")
        self.assertEqual(self.snap()["busy"], 0)

    def test_a_text_job_is_never_opened(self):
        self.q.worker("runner-a")
        self.q.claim("20261029T003000Z-note", "runner-a", origname="note.txt")
        busy = self.snap()["workers"][0]
        self.assertEqual((busy["state"], busy["project"]), ("busy", None))

    def test_waiting_skips_what_process_inbox_never_claims(self):
        self.q.write("inbox/a.json", '{"prompt": "x", "project": "drosera"}')
        self.q.write("inbox/b.txt", SECRET)
        for skipped in (".hidden", "c.json.partial", "d.tmp", "e.swp", "f.owner"):
            self.q.write("inbox/" + skipped, "")
        snap = self.snap()
        self.assertEqual(snap["waiting"], 2)
        self.assertEqual(snap["waiting_projects"], ["drosera"])

    def test_runs_of_the_last_day_newest_first(self):
        self.q.run("recent", started_ago_h=1, project="brasenia")
        self.q.run("broke", started_ago_h=3, exit_code=7, limit="timeout", project="kalmia")
        self.q.run("old", started_ago_h=30)
        self.q.run("running", started_ago_h=0.5, finished=False)
        runs = self.snap()["runs"]
        self.assertEqual([(r["project"], r["exit"], r["limit"]) for r in runs],
                         [("brasenia", 0, None), ("kalmia", 7, "timeout")])
        self.assertEqual(runs[0]["duration"], 120)

    def test_a_run_that_started_before_the_window_but_finished_in_it(self):
        self.q.run("long", started_ago_h=25, duration_s=2 * 3600)
        self.assertEqual(len(self.snap()["runs"]), 1)

    def test_finished_meta_is_cached_and_unfinished_is_not(self):
        done = self.q.run("done", started_ago_h=1)
        going = self.q.run("going", started_ago_h=0.2, finished=False)
        cache = {}
        self.snap(cache)
        self.assertEqual(set(cache), {done + ".meta"})
        self.assertNotIn(going + ".meta", cache)

    def test_a_missing_queue_reads_as_empty(self):
        snap = queue.snapshot(self.root + "/nope", NOW)
        self.assertEqual((snap["alive"], snap["busy"], snap["waiting"], snap["runs"]), (0, 0, 0, []))


if __name__ == "__main__":
    unittest.main()
