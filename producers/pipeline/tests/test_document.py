import json
import unittest

from helpers import fixture
from pipeline_producer.document import STAGES, DocumentError, in_flight, load, stages


def serve(body):
    return lambda url: body if isinstance(body, bytes) else json.dumps(body).encode()


class LoadTests(unittest.TestCase):
    def test_example_parses(self):
        generated_at, repos = load(serve(fixture("example")), "u")
        self.assertEqual(generated_at.isoformat(), "2026-10-07T22:10:00+00:00")
        self.assertEqual([r["repo"] for r in repos], ["lentago/drosera"])

    def test_rejects_what_the_pane_cannot_use(self):
        bad = [
            b"not json",
            [],
            dict(fixture("example"), schema=2),
            dict(fixture("example"), generated_at="yesterday"),
            dict(fixture("example"), generated_at="2026-10-07T22:10:00"),  # no offset
            dict(fixture("example"), repos={"lentago/drosera": {}}),
            dict(fixture("example"), repos=["lentago/drosera"]),
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                with self.assertRaises(DocumentError):
                    load(serve(body), "u")

    def test_network_failure_is_a_document_error(self):
        def fetch(url):
            raise OSError("connection refused")
        with self.assertRaises(DocumentError):
            load(fetch, "u")


class InFlightTests(unittest.TestCase):
    def test_example_has_nothing_in_flight(self):
        self.assertEqual(in_flight(fixture("example")["repos"]), [])

    def test_oldest_first_and_unknown_since_last(self):
        repos = [
            {"repo": "a/new", "in_flight": True, "in_flight_since": "2026-10-07T22:05:00Z"},
            {"repo": "a/none", "in_flight": True, "in_flight_since": None},
            {"repo": "a/old", "in_flight": True, "in_flight_since": "2026-10-07T21:00:00Z"},
            {"repo": "a/idle", "in_flight": False, "in_flight_since": None},
            {"repo": "a/truthy", "in_flight": "yes"},
        ]
        self.assertEqual([r["repo"] for r in in_flight(repos)], ["a/old", "a/new", "a/none"])

    def test_stages_always_six_in_order(self):
        filled = stages({"stages": [{"stage": "live", "state": 1}, {"stage": "bogus"}]})
        self.assertEqual([s["stage"] for s in filled], list(STAGES))
        self.assertEqual(filled[-1]["state"], 1)
        self.assertEqual(filled[0]["state"], 0)


if __name__ == "__main__":
    unittest.main()
