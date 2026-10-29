import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from zoneinfo import ZoneInfo

from helpers import FIXTURES, fixture

from family_brief_producer.doc import main, render_doc

TZ = ZoneInfo("America/New_York")


class RenderDoc(unittest.TestCase):

    def test_the_day_first(self):
        page = render_doc(fixture(), TZ)
        self.assertIn("<h1>Family Brief: Sunday, October 25</h1>", page)
        self.assertIn("Morning edition, 7:09 AM Eastern · 1 item today · 2 pickup gaps this week", page)
        self.assertIn("<h2>Sunday, October 25</h2>", page)
        self.assertIn('<b style="color:#b06000">Coverage:</b>', page)
        self.assertIn("No kid handoffs today.", page)
        self.assertIn("<b>10:30 - 11:30 AM</b> · ", page)
        self.assertIn("Brunch with a friend", page)
        self.assertIn("the diner", page)

    def test_one_persons_colour_is_darkened_for_a_white_page(self):
        page = render_doc(fixture(), TZ)
        # Jordan's #f06292, at 62%
        self.assertIn('<b style="color:#943c5a">Jordan:</b>', page)

    def test_decisions_todos_and_the_rest_of_the_week(self):
        page = render_doc(fixture(), TZ)
        self.assertIn("<h2>Needs a decision</h2>", page)
        self.assertIn('<p style="margin: 12pt 0 2pt 0"><b>Who does pickups Mon 10/26?</b>', page)
        self.assertIn("Source: Jordan&#x27;s calendar", page)
        self.assertIn("<li><b>Buy</b> Plates for the class party.", page)
        self.assertIn("Due Fri 10/30", page)
        self.assertIn("<h3>Monday, October 26</h3>", page)
        self.assertIn("<h3>Tuesday, October 27</h3>", page)
        # the title, today's heading and the "Generated" footer: never repeated under the week
        self.assertEqual(page.count("Sunday, October 25"), 3)

    def test_flags_coming_up_and_fyi(self):
        doc = fixture()
        doc["week"] = [{"date": "2026-10-26", "flag": "gap"}, {"date": "2026-10-27", "flag": "none"}]
        doc["horizon"] = [{"when": "Fri 11/6", "people": ["alex"], "who": "Alex", "what": "Dentist, 10:45 AM",
                           "note": "Needs an adult"}]
        doc["fyi"] = ["The library is closed Monday.", "", 7]
        page = render_doc(doc, TZ)
        self.assertIn("<h3>Monday, October 26 (coverage gap)</h3>", page)
        self.assertIn("<h3>Tuesday, October 27</h3>", page)
        self.assertIn("<h2>Coming up</h2>", page)
        self.assertIn("Fri 11/6 · Dentist, 10:45 AM", page)
        self.assertIn("(Needs an adult)", page)
        self.assertIn("<h2>FYI</h2><ul><li>The library is closed Monday.</li></ul>", page)

    def test_empty_sections_are_left_out(self):
        doc = fixture()
        for key in ("decisions", "todos", "this_week", "horizon", "fyi"):
            doc[key] = []
        doc["today"] = {"items": []}
        page = render_doc(doc, TZ)
        for heading in ("Needs a decision", "To do", "The rest of the week", "Coming up", "FYI", "Coverage"):
            self.assertNotIn(heading, page)
        self.assertIn("Nothing on the calendar.", page)

    def test_every_paragraph_carries_its_spacing(self):
        # Google Docs' import drops default paragraph spacing; inline margins survive it.
        page = render_doc(fixture(), TZ)
        self.assertEqual(page.count("<p>"), 0)
        self.assertIn('<p style="margin: 0 0 6pt 0"><b>10:30 - 11:30 AM</b>', page)
        self.assertIn('<p style="margin: 0 0 6pt 0; text-decoration: line-through"><b>5:00 - 6:00 PM</b>', page)

    def test_the_same_brief_renders_the_same_bytes(self):
        self.assertEqual(render_doc(fixture(), TZ), render_doc(fixture(), TZ))

    def test_text_is_escaped_and_there_are_no_scripts(self):
        doc = fixture()
        doc["today"]["items"][0]["what"] = "<script>alert(1)</script> & co"
        page = render_doc(doc, TZ)
        self.assertNotIn("<script", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", page)

    def test_the_footer_says_when_the_brief_was_generated(self):
        page = render_doc(dict(fixture(), footer="All times US Eastern."), TZ)
        self.assertIn("All times US Eastern. Generated Sunday, October 25 at 7:10 AM.", page)


class Cli(unittest.TestCase):

    def test_prints_the_document(self):
        out = StringIO()
        with redirect_stdout(out):
            code = main([os.path.join(FIXTURES, "example", "latest.json")])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("<!DOCTYPE html>"))
        self.assertIn("Family Brief: Sunday, October 25", out.getvalue())

    def test_a_bad_source_fails_without_output(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as fh:
            fh.write('{"schema": 2}')
            fh.flush()
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main([fh.name])
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertIn("not a schema-1 document", err.getvalue())


if __name__ == "__main__":
    unittest.main()
