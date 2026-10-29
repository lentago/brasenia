import json
import os
import tempfile
import unittest

from helpers import SLOTS

from grafana_producer import slots
from grafana_producer.slots import SlotError, parse


def one(**fields):
    raw = {"pane": "grafana-x", "uid": "abc-123", "title": "X"}
    raw.update(fields)
    return parse({"slots": [raw]})[0]


class SlotsTest(unittest.TestCase):

    def test_the_fixture_loads_with_defaults_filled_in(self):
        infra, network = slots.load(SLOTS)
        self.assertEqual((infra.pane, infra.uid, infra.title), ("grafana-infra", "firewalla-infra-health",
                                                                "Infrastructure health"))
        self.assertEqual(infra.size, (1232, 610))
        self.assertEqual((infra.theme, infra.refresh_s, infra.crop_px, infra.scale, infra.dwell_s),
                         ("dark", 300, 40, 1, 60))
        self.assertEqual((infra.time_from, infra.time_to, infra.vars, infra.org_id),
                         ("now-6h", "now", {}, 1))
        self.assertEqual(network.size, (1920, 950))
        self.assertEqual((network.refresh_s, network.scale, network.vars), (600, 2, {"host": "pve4"}))

    def test_required_fields(self):
        for key in ("pane", "uid", "title"):
            raw = {"pane": "grafana-x", "uid": "abc", "title": "X"}
            del raw[key]
            with self.assertRaisesRegex(SlotError, repr(key)):
                parse({"slots": [raw]})

    def test_bad_values_are_refused(self):
        for fields in ({"pane": "Grafana X"}, {"uid": "../admin"}, {"title": " "},
                       {"theme": "blue"}, {"refresh_s": 30}, {"refresh_s": True},
                       {"size": [999, 610]}, {"size": [1232, 459]}, {"size": [3001, 610]},
                       {"size": [1232, 2961]}, {"size": [1232]}, {"crop_px": 201},
                       {"scale": 4}, {"scale": 1.5}, {"vars": {"a b": "x"}}, {"vars": {"a": 1}},
                       {"dwell_s": 0}, {"colour": "red"}):
            with self.subTest(fields=fields), self.assertRaises(SlotError):
                one(**fields)

    def test_size_and_crop_together_meet_grafana_clouds_minimum_height(self):
        self.assertEqual(one(size=[1000, 460], crop_px=40).size, (1000, 460))
        with self.assertRaises(SlotError):
            one(size=[1000, 460], crop_px=0)

    def test_two_slots_cannot_write_one_pane(self):
        raw = {"pane": "grafana-x", "uid": "a", "title": "X"}
        with self.assertRaisesRegex(SlotError, "two slots"):
            parse({"slots": [raw, dict(raw, uid="b")]})

    def test_an_unreadable_file_is_a_slot_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "slots.json")
            with self.assertRaises(SlotError):
                slots.load(path)
            with open(path, "w") as fh:
                json.dump([], fh)
            with self.assertRaisesRegex(SlotError, '"slots" list'):
                slots.load(path)


if __name__ == "__main__":
    unittest.main()
