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

    def test_the_default_size_fills_the_frame_at_one_and_a_half(self):
        self.assertEqual(render.fit((1232, 610), 40), (36, 1848, 915, 975))

    def test_a_larger_layout_is_scaled_to_fit_and_centred(self):
        left, width, height, image_h = render.fit((1920, 1080), 40)
        self.assertEqual((width, height), (1627, 915))
        self.assertEqual(left, 36 + (1848 - 1627) // 2)
        self.assertEqual(image_h, round(1120 * 915 / 1080))

    def test_the_frame_and_footer_keep_off_the_clock_corner(self):
        for size in ((1232, 610), (1000, 460), (3000, 500), (1000, 2960)):
            left, width, height, _ = render.fit(size, 40)
            self.assertLessEqual(left + width, 1920 - 36)
            self.assertLessEqual(36 + height, 1080 - 75 - 36)   # ends above the clock band

    def test_the_page_declares_the_1920_canvas(self):
        page = self.page()
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', page)
        self.assertIn("width: 1920px; height: 1080px;", page)
        self.assertNotIn("zoom", page)
        self.assertIn("font-size: 30px", page)

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
