import re
import unittest
from datetime import datetime, timezone

from focus_producer.render import MAX_ROWS, render, restamp

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def pr(n, **kw):
    d = {"number": n, "title": "PR number %d" % n, "author": "claude",
         "created_at": "2026-10-07T09:00:00Z", "draft": False,
         "checks": "passing", "review": "no review"}
    d.update(kw)
    return d


def page(pulls=(), main=None, pipeline=None):
    data = {"pulls": list(pulls),
            "main": main or {"conclusion": "success", "name": "docs-check",
                             "updated_at": "2026-10-07T11:30:00Z"}}
    return render("lentago/brasenia", data, pipeline, NOW, NOW)


def px(css, selector, prop):
    block = re.search(r"^" + re.escape(selector) + r"\s*\{([^}]*)\}", css, re.M).group(1)
    return int(re.search(prop + r":\s*(\d+)px", block).group(1))


class RenderTests(unittest.TestCase):
    def test_single_band(self):
        html = page([pr(1)])
        css = re.search(r"<style>(.*)</style>", html, re.S).group(1)
        self.assertEqual(px(css, "body", "width"), 1920)
        self.assertEqual(px(css, "body", "height"), 1080)
        self.assertIn('<meta name="brasenia-canvas" content="1920x1080">', html)
        self.assertNotIn("zoom", html)
        self.assertIn("overflow: hidden", re.search(r"^body \{([^}]*)\}", css, re.M).group(1))

    def test_layout_fits_band_and_clears_clock_corner(self):
        css = re.search(r"<style>(.*)</style>", page(), re.S).group(1)
        top, main_h = px(css, ".main", "top"), px(css, ".main", "height")
        header = px(css, "header", "height")
        h1 = px(css, "h1", "line-height")
        line = px(css, ".line", "line-height")
        self.assertLessEqual(h1 + 3 * line, header)
        content = header + px(css, "th", "height") + MAX_ROWS * px(css, "td", "height") \
            + px(css, ".more, .empty", "height")
        self.assertLessEqual(content, main_h)
        self.assertGreaterEqual(top, 36)
        self.assertLessEqual(top + main_h, 1080 - 75 - 36)  # above the clock strip
        foot_left, foot_w = px(css, ".foot", "left"), px(css, ".foot", "width")
        self.assertLessEqual(foot_left + foot_w, 1920 - 330 - 36)  # left of the clock corner
        self.assertGreaterEqual(px(css, ".foot", "bottom"), 36)

    def test_min_text_size(self):
        css = re.search(r"<style>(.*)</style>", page(), re.S).group(1)
        for size in re.findall(r"font-size:\s*(\d+)px", css):
            self.assertGreaterEqual(int(size), 20)

    def test_no_external_references(self):
        html = page([pr(1, title='x <script src="http://evil/x.js"></script> url(http://a)')])
        tags = " ".join(re.findall(r"<[^>]*>", html))
        css = re.search(r"<style>(.*)</style>", html, re.S).group(1)
        self.assertNotRegex(tags, r"(?i)<script|<link|<img|<iframe|<object|<embed|\bsrc=|\bhref=|http")
        self.assertNotRegex(css, r"(?i)@import|url\(|http")
        self.assertIn("&lt;script", html)

    def test_palette(self):
        html = page()
        for colour in ("#0e2b1a", "#f3f0e8", "#cdd6d0", "#E0A81C"):
            self.assertIn(colour, html)

    def test_content(self):
        html = page([pr(12, title="Focus producer", author="octo", draft=True,
                        checks="failing", review="changes requested")],
                    pipeline={"repo": "lentago/brasenia", "sha": "5afd3f4abcdef",
                              "stage": "review", "since": "2026-10-07T11:00:00Z"})
        for text in ("<h1>brasenia</h1>", "#12", "Focus producer", "octo", "3h", "[draft]",
                     "failing", "changes requested", "success", "docs-check",
                     "pipeline: <b>review</b> · 5afd3f4", "data as of "):
            self.assertIn(text, html)

    def test_pipeline_row_omitted_when_absent(self):
        self.assertNotIn("pipeline:", page())

    def test_row_cap(self):
        html = page([pr(n) for n in range(1, MAX_ROWS + 4)])
        self.assertEqual(html.count("<tr><td>#"), MAX_ROWS)
        self.assertIn("+3 more", html)

    def test_empty(self):
        self.assertIn("No open pull requests.", page())

    def test_restamp_keeps_data_and_updates_stamp(self):
        old = page([pr(5)])
        later = datetime(2026, 10, 7, 12, 7, tzinfo=timezone.utc)
        new = restamp(old, later)
        self.assertIn("PR number 5", new)
        self.assertIn("GitHub unavailable, last tried %s" % later.astimezone().strftime("%H:%M"), new)
        self.assertIn("data as of %s" % NOW.astimezone().strftime("%H:%M"), new)
        # A second failure replaces the note rather than stacking another.
        newer = restamp(new, later)
        self.assertEqual(newer.count("GitHub unavailable"), 1)
        strip = lambda h: re.sub(r"<!--asof-->.*?<!--/asof-->", "", h)  # noqa: E731
        self.assertEqual(strip(newer), strip(old))
        self.assertIsNone(restamp("<html></html>", later))


    def test_no_push_run_is_not_labelled_twice(self):
        data = {"pulls": [], "main": None}
        text = render("lentago/brasenia", data, None, NOW, NOW)
        self.assertIn("main: <b>no push run</b>", text)
        self.assertNotIn("main: main:", text)

    def test_clock_times_use_the_given_zone(self):
        from zoneinfo import ZoneInfo
        data = {"pulls": [], "main": None}
        row = {"repo": "lentago/brasenia", "stage": "review", "since": "2026-10-07T11:00:00Z"}
        text = render("lentago/brasenia", data, row, NOW, NOW, ZoneInfo("America/New_York"))
        self.assertIn("data as of 08:00", text)      # 12:00 UTC is 08:00 EDT
        self.assertIn("since 07:00", text)
        later = datetime(2026, 10, 7, 12, 30, 0, tzinfo=timezone.utc)
        self.assertIn("last tried 08:30", restamp(text, later, ZoneInfo("America/New_York")))


if __name__ == "__main__":
    unittest.main()
