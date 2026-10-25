import json
import unittest
from datetime import date

from helpers import fixture, with_date
from family_brief_producer.document import DocumentError, days, is_fresh, load, touching

SUN, MON, TUE = date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27)


def fetch_of(body):
    return lambda url: body if isinstance(body, bytes) else json.dumps(body).encode()


class LoadTests(unittest.TestCase):
    def test_accepts_the_fixture(self):
        self.assertEqual(load(fetch_of(fixture()), "x")["date"], "2026-10-25")

    def test_rejects_other_schemas_and_bad_dates(self):
        for body in ({"schema": 2, "date": "2026-10-25"}, {"schema": True, "date": "2026-10-25"},
                     {"schema": 1, "date": "10/25"},
                     {"schema": 1}, [1, 2], b"not json"):
            with self.subTest(body=body), self.assertRaises(DocumentError):
                load(fetch_of(body), "x")

    def test_fetch_failure_is_a_document_error(self):
        def broken(url):
            raise OSError("connection refused")
        with self.assertRaises(DocumentError):
            load(broken, "x")


class DayTests(unittest.TestCase):
    def test_brief_day_uses_today_block_and_coverage(self):
        today, coverage, tomorrow = days(fixture(), SUN)
        self.assertEqual([i["what"] for i in today], ["Brunch with a friend"])
        self.assertIn("No kid handoffs", coverage)
        self.assertEqual(len(tomorrow), 5)

    def test_day_after_uses_this_week_and_drops_coverage(self):
        today, coverage, tomorrow = days(fixture(), MON)
        self.assertEqual(len(today), 5)
        self.assertIsNone(coverage)
        self.assertEqual(len(tomorrow), 7)

    def test_a_day_the_brief_does_not_list_is_empty(self):
        _, _, tomorrow = days(fixture(), TUE)
        self.assertEqual(tomorrow, [])

    def test_freshness_is_its_own_day_and_the_next(self):
        doc = fixture()
        self.assertTrue(is_fresh(doc, SUN))
        self.assertTrue(is_fresh(doc, MON))
        self.assertFalse(is_fresh(doc, TUE))
        self.assertFalse(is_fresh(with_date(doc, "2026-10-26"), SUN))

    def test_touching_matches_dates(self):
        titles = [d["title"] for d in touching(fixture()["decisions"], (SUN, MON), "dates")]
        self.assertEqual(titles, ["Who does pickups Mon 10/26?"])
