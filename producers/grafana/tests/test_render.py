import base64
import re
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from helpers import make_png

from grafana_producer import render
from grafana_producer.slots import parse


def slot(**fields):
    raw = {"pane": "grafana-x", "uid": "abc", "title": "Infra <health>"}
    raw.update(fields)
    return parse({"slots": [raw]})[0]


class RenderTest(unittest.TestCase):

    def page(self, **fields):
        return render.page(slot(**fields), make_png(8, 8),
                           datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc),
                           ZoneInfo("America/New_York"))

    def test_the_default_size_fills_the_frame_one_to_one(self):
        self.assertEqual(render.fit((1232, 610), 40), (24, 1232, 610, 650))

    def test_a_larger_layout_is_scaled_to_fit_and_centred(self):
        left, width, height, image_h = render.fit((1920, 1080), 40)
        self.assertEqual((width, height), (1084, 610))
        self.assertEqual(left, 24 + (1232 - 1084) // 2)
        self.assertEqual(image_h, round(1120 * 610 / 1080))

    def test_the_frame_and_footer_keep_off_the_clock_corner(self):
        for size in ((1232, 610), (1000, 460), (3000, 500), (1000, 2960)):
            left, width, height, _ = render.fit(size, 40)
            self.assertLessEqual(left + width, 1280 - 24)
            self.assertLessEqual(24 + height, 720 - 50 - 24)   # ends above the clock band

    def test_the_page_is_self_contained_and_inlines_the_png(self):
        page = self.page()
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("data:image/png;base64," + base64.b64encode(make_png(8, 8)).decode(), page)
        self.assertIsNone(re.search(r"\bsrc\s*=\s*[\"']?https?:", page))
        self.assertNotIn("<script", page)
        self.assertNotIn("<link", page)

    def test_the_footer_names_the_dashboard_and_the_render_time(self):
        page = self.page()
        self.assertIn("Infra &lt;health&gt; · Grafana · as of 8:40 PM", page)
        self.assertNotIn("<health>", page)

    def test_a_new_image_is_a_new_page(self):
        when, tz = datetime(2026, 10, 29, tzinfo=timezone.utc), ZoneInfo("America/New_York")
        self.assertNotEqual(render.page(slot(), make_png(8, 8), when, tz),
                            render.page(slot(), make_png(8, 9), when, tz))


if __name__ == "__main__":
    unittest.main()
