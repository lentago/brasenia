import json
import os
import shutil
import tempfile
import http.client
import unittest
from datetime import timedelta
from unittest import mock

from helpers import SLOTS, STACK, TOKEN, Clock, FakeGrafana

from grafana_producer import producer, slots
from grafana_producer.grafana import png_size
from grafana_producer.producer import Producer


class ProducerTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.token_file = os.path.join(self.root, "grafana-token")
        self.webroot = os.path.join(self.root, "www")
        self.fake = FakeGrafana()
        self.clock = Clock()
        self.slots = slots.load(SLOTS)

    def seed_token(self, token=TOKEN):
        with open(self.token_file, "w") as fh:
            fh.write(token + "\n")

    def make(self, slot_list=None):
        return Producer(self.webroot, self.token_file, STACK,
                        self.slots if slot_list is None else slot_list,
                        tz="America/New_York", transport=self.fake, clock=self.clock)

    def path(self, pane_id, name):
        return os.path.join(self.webroot, "viewport", "panes", pane_id, name)

    def pane(self, pane_id, name="manifest.json"):
        path = self.path(pane_id, name)
        if not os.path.exists(path):
            return None
        mode = "rb" if name.endswith(".png") else "r"
        with open(path, mode) as fh:
            return json.load(fh) if name.endswith(".json") else fh.read()

    def test_no_token_writes_nothing_and_says_so_once(self):
        p = self.make()
        with self.assertLogs(producer.log, "WARNING") as logs:
            self.assertEqual(p.cycle(), 2)      # --once reads this as failure
            p.cycle()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("no Grafana token", logs.output[0])
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(os.path.exists(self.webroot))

    def test_each_slot_becomes_a_pane_with_a_png_and_a_page(self):
        self.seed_token()
        self.assertEqual(self.make().cycle(), 0)
        self.assertEqual(self.pane("grafana-infra"), {
            "schema": 1, "class": "ambient", "title": "Infrastructure health",
            "created": "2026-10-29T00:40:00Z", "ttl_minutes": 15,
            "author": "grafana-producer@pub", "origin": "operator", "dwell_s": 60})
        self.assertEqual(self.pane("grafana-network")["ttl_minutes"], 30)
        self.assertEqual(self.pane("grafana-network")["dwell_s"], 45)
        self.assertEqual(png_size(self.pane("grafana-infra", "dashboard.png")), (1232, 650))
        self.assertEqual(png_size(self.pane("grafana-network", "dashboard.png")), (3840, 1980))
        for pane_id in ("grafana-infra", "grafana-network"):
            page = self.pane(pane_id, "pane.html")
            self.assertIn("data:image/png;base64,", page)
            self.assertNotIn(TOKEN, page)
            files = os.listdir(os.path.dirname(self.path(pane_id, "x")))
            self.assertEqual(sorted(files), ["dashboard.png", "manifest.json", "pane.html"])

    def test_slots_render_on_their_own_cadence(self):
        self.seed_token()
        p = self.make()
        p.cycle()
        self.assertEqual(len(self.fake.calls), 2)
        self.clock.advance(299)
        p.cycle()
        self.assertEqual(len(self.fake.calls), 2)
        self.clock.advance(1)
        p.cycle()
        self.assertEqual(len(self.fake.calls), 3)                   # infra, at 300 s
        self.assertIn("/render/d/firewalla-infra-health?", self.fake.calls[-1])
        self.assertEqual(self.pane("grafana-infra")["created"], "2026-10-29T00:45:00Z")
        self.assertEqual(self.pane("grafana-network")["created"], "2026-10-29T00:40:00Z")
        self.clock.advance(300)
        p.cycle()
        self.assertEqual(len(self.fake.calls), 5)                   # both, at 600 s

    def test_a_failed_render_keeps_the_pane_and_backs_off(self):
        self.seed_token()
        p = self.make(self.slots[:1])
        p.cycle()
        page = self.pane("grafana-infra", "pane.html")
        self.fake.status = 500
        waits = []
        for _ in range(6):
            self.clock.now = p.next_at["grafana-infra"]
            before = self.clock.now
            self.assertEqual(p.cycle(), 1)
            waits.append((p.next_at["grafana-infra"] - before).total_seconds())
        self.assertEqual(waits, [300, 600, 1200, 2400, 3600, 3600])
        self.assertEqual(self.pane("grafana-infra", "pane.html"), page)     # untouched
        self.assertEqual(self.pane("grafana-infra")["created"], "2026-10-29T00:40:00Z")
        self.fake.status = 200
        self.clock.now = p.next_at["grafana-infra"]
        self.assertEqual(p.cycle(), 0)
        self.assertEqual(p.failures, {})

    def test_429_waits_at_least_as_long_as_grafana_asks(self):
        self.seed_token()
        p = self.make(self.slots[:1])
        self.fake.status, self.fake.headers = 429, {"Retry-After": "900"}
        p.cycle()
        self.assertEqual((p.next_at["grafana-infra"] - self.clock()).total_seconds(), 900)

    def test_a_revoked_token_leaves_the_panes_to_their_ttl(self):
        self.seed_token()
        p = self.make()
        p.cycle()
        self.seed_token("revoked")
        self.clock.advance(600)
        self.assertEqual(p.cycle(), 2)
        self.assertEqual(self.pane("grafana-infra")["created"], "2026-10-29T00:40:00Z")

    def test_another_authors_pane_is_left_alone(self):
        self.seed_token()
        os.makedirs(os.path.dirname(self.path("grafana-infra", "x")))
        with open(self.path("grafana-infra", "manifest.json"), "w") as fh:
            json.dump({"author": "chris@desk"}, fh)
        with self.assertLogs(producer.log, "WARNING"):
            self.make(self.slots[:1]).cycle()
        self.assertEqual(self.pane("grafana-infra"), {"author": "chris@desk"})
        self.assertIsNone(self.pane("grafana-infra", "dashboard.png"))

    def test_ttl_covers_three_refreshes_and_at_least_ten_minutes(self):
        self.assertEqual(producer.ttl_minutes(60), 10)
        self.assertEqual(producer.ttl_minutes(300), 15)
        self.assertEqual(producer.ttl_minutes(610), 31)

    def test_a_token_with_whitespace_inside_is_rejected_without_being_echoed(self):
        secret = "sekrit-part1\nsekrit-part2"
        self.seed_token(secret)
        p = self.make()
        with self.assertLogs(producer.log, "WARNING") as logs:
            self.assertEqual(p.cycle(), 2)
        self.assertEqual(self.fake.calls, [])
        self.assertNotIn("sekrit", "\n".join(logs.output))

    def test_a_transport_error_that_carries_the_token_is_never_logged(self):
        # urllib raises ValueError("Invalid header value b'Bearer …'") for such a header.
        def transport(url, headers, timeout=None):
            raise ValueError("Invalid header value %r" % headers["Authorization"].encode())

        self.seed_token()
        p = Producer(self.webroot, self.token_file, STACK, self.slots, transport=transport,
                     clock=self.clock)
        with self.assertLogs(producer.log, "INFO") as logs:
            self.assertEqual(p.cycle(), 2)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertIn("ValueError", "\n".join(logs.output))
        self.assertEqual(set(p.failures), {"grafana-infra", "grafana-network"})

    def test_any_failure_of_one_slot_backs_it_off_and_leaves_the_others_alone(self):
        self.seed_token()
        for error in (http.client.IncompleteRead(b"x"), http.client.BadStatusLine("x"),
                      RuntimeError("boom"), TimeoutError("slow")):
            with self.subTest(error=type(error).__name__):
                calls = []

                def transport(url, headers, timeout=None, error=error, calls=calls):
                    calls.append(url)
                    if "firewalla-infra-health" in url:
                        raise error
                    return self.fake(url, headers, timeout)

                p = Producer(self.webroot, self.token_file, STACK, self.slots, transport=transport,
                             clock=self.clock)
                self.assertEqual(p.cycle(), 1)
                self.assertEqual(len(calls), 2)                     # the other slot still rendered
                self.assertIsNotNone(self.pane("grafana-network"))
                self.assertEqual(p.failures, {"grafana-infra": 1})
                self.assertEqual(p.next_at["grafana-infra"], self.clock() + timedelta(seconds=300))
                self.assertEqual(p.cycle(), 0)                      # not retried at --interval

    def test_a_write_error_backs_the_slot_off_and_spares_the_others(self):
        self.seed_token()
        p = self.make()
        real = producer.write_atomic

        def flaky(path, data):
            if "grafana-infra" in path:
                raise PermissionError("denied")
            real(path, data)

        with mock.patch.object(producer, "write_atomic", flaky), \
                self.assertLogs(producer.log, "INFO") as logs:
            self.assertEqual(p.cycle(), 1)
        self.assertIn("could not write", logs.output[0])
        self.assertIsNotNone(self.pane("grafana-network"))
        self.assertEqual(p.failures, {"grafana-infra": 1})
        self.assertEqual(p.next_at["grafana-infra"], self.clock() + timedelta(seconds=300))

    def test_429_retry_after_pauses_every_slot(self):
        self.seed_token()
        p = self.make()
        self.fake.status, self.fake.headers = 429, {"Retry-After": "900"}
        self.assertEqual(p.cycle(), 1)
        self.assertEqual(len(self.fake.calls), 1)                   # the second slot was not tried
        self.fake.status = 200
        self.clock.advance(899)
        self.assertEqual(p.cycle(), 0)
        self.assertEqual(len(self.fake.calls), 1)
        self.clock.advance(1)
        self.assertEqual(p.cycle(), 0)                              # both due and fine again
        self.assertEqual(len(self.fake.calls), 3)
        self.assertIsNotNone(self.pane("grafana-network"))


if __name__ == "__main__":
    unittest.main()
