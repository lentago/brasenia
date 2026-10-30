"""Tests for bin/pane against a temp bus. Run from the repo root:
python3 -m unittest discover -s bin/tests"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

PANE_PATH = os.path.join(os.path.dirname(__file__), "..", "pane")
_loader = importlib.machinery.SourceFileLoader("pane_cli", PANE_PATH)
_spec = importlib.util.spec_from_loader("pane_cli", _loader)
pane = importlib.util.module_from_spec(_spec)
_loader.exec_module(pane)

# The compositor's own rules, for the link-pane cross-check.
import sys  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from compositor import rubric  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
PAGE = "<!doctype html><html><body><h1>look here</h1></body></html>\n"


class PaneCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bus = tmp.name
        self.page = os.path.join(self.bus, "demo.html")
        with open(self.page, "w") as f:
            f.write(PAGE)

    def run_cli(self, *argv, now=T0, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if stdin is not None:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = pane.main(["--bus", self.bus] + list(argv), now=now)
            else:
                code = pane.main(["--bus", self.bus] + list(argv), now=now)
        return code, out.getvalue(), err.getvalue()

    def claim(self, pane_id="demo", author="ann@a", *extra, **kw):
        return self.run_cli("claim", pane_id, "--class", "attention",
                            "--title", "look here", "--author", author,
                            *(list(extra) + [self.page]), **kw)

    def pane_dir(self, pane_id="demo"):
        return os.path.join(self.bus, "panes", pane_id)

    def manifest(self, pane_id="demo"):
        with open(os.path.join(self.pane_dir(pane_id), "manifest.json")) as f:
            return json.load(f)


class ClaimTests(PaneCase):
    def test_writes_both_files_and_prints_url(self):
        code, out, _ = self.claim()
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "http://pub.lan/viewport/panes/demo/pane.html")
        self.assertEqual(sorted(os.listdir(self.pane_dir())),
                         ["manifest.json", "pane.html"])
        m = self.manifest()
        self.assertEqual(m["schema"], 1)
        self.assertEqual(m["class"], "attention")
        self.assertEqual(m["created"], "2026-10-07T12:00:00Z")
        self.assertEqual(m["ttl_minutes"], 240)
        self.assertEqual(m["origin"], "operator")
        self.assertEqual(m["author"], "ann@a")
        self.assertNotIn("repo", m)

    def test_manifest_is_written_last_via_rename(self):
        order = []
        real = pane.os.replace

        def spy(src, dst):
            order.append((os.path.basename(src), os.path.basename(dst)))
            return real(src, dst)

        with mock.patch.object(pane.os, "replace", spy):
            self.claim()
        self.assertEqual(order, [("pane.html.partial", "pane.html"),
                                 ("manifest.json.partial", "manifest.json")])

    def test_options_and_stdin(self):
        code, _, _ = self.run_cli(
            "claim", "x1", "--class", "focus", "--title", "t", "--ttl", "5",
            "--origin", "fleet", "--repo", "lentago/brasenia",
            "--author", "ann@a", "-", stdin=PAGE)
        self.assertEqual(code, 0)
        m = self.manifest("x1")
        self.assertEqual((m["ttl_minutes"], m["origin"], m["repo"]),
                         (5, "fleet", "lentago/brasenia"))
        self.assertNotIn("dwell_s", m)

    def test_default_author(self):
        with mock.patch.object(pane, "default_author", lambda: "u@h"):
            self.run_cli("claim", "demo", "--class", "alert", "--title", "t",
                         self.page)
        self.assertEqual(self.manifest()["author"], "u@h")

    def test_class_defaults(self):
        for cls, ttl in (("alert", 60), ("activity", 60), ("focus", 10)):
            self.run_cli("claim", cls, "--class", cls, "--title", "t",
                         "--author", "a", self.page)
            self.assertEqual(self.manifest(cls)["ttl_minutes"], ttl)

    def test_class_without_default_ttl_needs_one(self):
        code, _, err = self.run_cli("claim", "d", "--class", "ambient",
                                    "--title", "t", self.page)
        self.assertEqual(code, 1)
        self.assertIn("--ttl", err)
        self.assertFalse(os.path.exists(self.pane_dir("d")))

    def test_the_retired_live_class_is_a_usage_error(self):
        # RTMP live ingest and its class are retired (#122).
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("claim", "d", "--class", "live", "--title", "t",
                         "--ttl", "5", self.page)
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(os.path.exists(self.pane_dir("d")))

    def test_nonfinite_ttl_and_the_retired_dwell_are_usage_errors(self):
        # --dwell went with rotation (ADR-0020, #121).
        for flag, value in (("--ttl", "nan"), ("--ttl", "inf"), ("--dwell", "30")):
            with self.assertRaises(SystemExit) as ctx:
                self.claim("d", "ann@a", flag, value)
            self.assertEqual(ctx.exception.code, 2)
            self.assertFalse(os.path.exists(self.pane_dir("d")))

    def test_overflowing_ttl_is_refused_not_written(self):
        code, _, err = self.claim("d", "ann@a", "--ttl", "1e300")
        self.assertEqual(code, 1)
        self.assertIn("--ttl", err)
        self.assertFalse(os.path.exists(self.pane_dir("d")))
        self.claim("ok", "ann@a")
        code, _, err = self.run_cli("renew", "ok", "--author", "ann@a",
                                    "--ttl", "1e300")
        self.assertEqual(code, 1)
        self.assertEqual(self.manifest("ok")["ttl_minutes"], 240)

    def test_bad_id(self):
        for bad in ("Demo", "_demo", "a/b", "..", "a" * 64, "a b"):
            code, _, err = self.claim(bad)
            self.assertEqual(code, 1, bad)
            self.assertIn("invalid pane id", err)
        self.assertFalse(os.path.exists(os.path.join(self.bus, "panes")))

    def test_max_length_id_ok(self):
        self.assertEqual(self.claim("a" * 63)[0], 0)

    def test_bad_class_is_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.run_cli("claim", "demo", "--class", "urgent",
                             "--title", "t", self.page)
        self.assertEqual(cm.exception.code, 2)

    def test_bad_class_refused_by_claim(self):
        with self.assertRaises(pane.Refused):
            pane.claim(self.bus, "demo", "urgent", "t", PAGE, T0, author="a")

    def test_empty_page_refused(self):
        code, _, err = self.run_cli("claim", "demo", "--class", "alert",
                                    "--title", "t", "-", stdin="  \n")
        self.assertEqual(code, 1)
        self.assertIn("empty", err)

    def test_external_references_refused_and_named(self):
        cases = (
            '<script src="https://cdn.example/x.js"></script>',
            '<SCRIPT\n src = "x.js">',
            '<link rel="stylesheet" href="style.css">',
            '<img src="http://example.com/a.png">',
        )
        for bad in cases:
            code, _, err = self.run_cli(
                "claim", "demo", "--class", "alert", "--title", "t", "-",
                stdin="<html><body>%s</body></html>" % bad)
            self.assertEqual(code, 1, bad)
            self.assertIn("external reference", err)
            self.assertIn("src" if "src" in bad.lower() else "href",
                          err.lower())
            self.assertFalse(os.path.exists(self.pane_dir()))

    def test_inline_script_and_style_allowed(self):
        page = "<style>a{}</style><script>var x=1</script>"
        code, _, _ = self.run_cli("claim", "demo", "--class", "alert",
                                  "--title", "t", "-", stdin=page)
        self.assertEqual(code, 0)

    def test_missing_page_file_refused(self):
        code, _, err = self.run_cli("claim", "demo", "--class", "alert",
                                    "--title", "t", "/nonexistent.html")
        self.assertEqual(code, 1)
        self.assertIn("cannot read page", err)

    def test_missing_bus_refused_and_not_created(self):
        missing = os.path.join(self.bus, "nope")
        code = pane.main(["--bus", missing, "claim", "demo", "--class",
                          "alert", "--title", "t", self.page], now=T0)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(missing))

    def test_reclaim_own_pane_ok_other_authors_refused(self):
        self.assertEqual(self.claim()[0], 0)
        self.assertEqual(self.claim()[0], 0)
        code, _, err = self.claim("demo", "bob@b")
        self.assertEqual(code, 1)
        self.assertIn("ann@a", err)
        self.assertEqual(self.manifest()["author"], "ann@a")

    def test_viewport_dir_env(self):
        with mock.patch.dict(os.environ, {"VIEWPORT_DIR": self.bus}):
            args = pane.build_parser().parse_args(["ls"])
        self.assertEqual(args.bus, self.bus)


class RenewReleaseTests(PaneCase):
    def test_renew_slides_created_and_keeps_ttl(self):
        self.claim()
        later = T0 + timedelta(minutes=100)
        self.assertEqual(self.run_cli("renew", "demo", "--author", "ann@a",
                                      now=later)[0], 0)
        m = self.manifest()
        self.assertEqual(m["created"], "2026-10-07T13:40:00Z")
        self.assertEqual(m["ttl_minutes"], 240)

    def test_renew_with_ttl(self):
        self.claim()
        self.run_cli("renew", "demo", "--ttl", "15", "--author", "ann@a")
        self.assertEqual(self.manifest()["ttl_minutes"], 15)

    def test_renew_refuses_other_author(self):
        self.claim()
        code, _, err = self.run_cli("renew", "demo", "--author", "bob@b",
                                    now=T0 + timedelta(minutes=5))
        self.assertEqual(code, 1)
        self.assertIn("ann@a", err)
        self.assertEqual(self.manifest()["created"], "2026-10-07T12:00:00Z")

    def test_release_removes_only_own(self):
        self.claim("mine", "ann@a")
        self.claim("theirs", "bob@b")
        self.assertEqual(self.run_cli("release", "theirs", "--author",
                                      "ann@a")[0], 1)
        self.assertTrue(os.path.isdir(self.pane_dir("theirs")))
        self.assertEqual(self.run_cli("release", "mine", "--author",
                                      "ann@a")[0], 0)
        self.assertFalse(os.path.exists(self.pane_dir("mine")))
        self.assertTrue(os.path.isdir(self.pane_dir("theirs")))

    def test_no_force_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.run_cli("release", "demo", "--force")
        self.assertEqual(cm.exception.code, 2)

    def test_missing_pane_and_bad_id_refused(self):
        for cmd in ("renew", "release"):
            code, _, err = self.run_cli(cmd, "ghost", "--author", "a")
            self.assertEqual(code, 1)
            self.assertIn("no such pane", err)
            code, _, err = self.run_cli(cmd, "../x", "--author", "a")
            self.assertEqual(code, 1)
            self.assertIn("invalid pane id", err)

    def test_malformed_manifest_cannot_be_released(self):
        os.makedirs(self.pane_dir("bad"))
        with open(os.path.join(self.pane_dir("bad"), "manifest.json"),
                  "w") as f:
            f.write("{nope")
        code, _, err = self.run_cli("release", "bad", "--author", "a")
        self.assertEqual(code, 1)
        self.assertIn("does not parse", err)
        self.assertTrue(os.path.isdir(self.pane_dir("bad")))


class LinkTests(PaneCase):
    """claim --url: a link pane (ADR-0016), a manifest naming a web page."""

    URL = "https://github.com/lentago/brasenia/pull/93"

    def link(self, *extra, pane_id="pr-93", author="ann@a"):
        return self.run_cli("claim", pane_id, "--class", "attention", "--title",
                            "PR 93", "--author", author, "--url", self.URL, *extra)

    def test_writes_only_a_manifest_and_prints_the_url(self):
        code, out, err = self.link()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), self.URL)
        self.assertEqual(sorted(os.listdir(self.pane_dir("pr-93"))), ["manifest.json"])
        self.assertEqual(self.manifest("pr-93")["source"], {"url": self.URL})

    def test_display_options(self):
        code, _, err = self.link("--theme", "light", "--viewport", "1920x1080",
                                 "--refresh", "300")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.manifest("pr-93")["source"],
                         {"url": self.URL, "theme": "light",
                          "viewport": [1920, 1080], "refresh_s": 300})

    def test_refusals(self):
        cases = [
            (["--url", "ftp://x.test/"], "http(s)"),
            (["--url", "https://ann:pw@x.test/"], "user or password"),
            (["--url", "https://x.test/a b"], "not a URL"),
            (["--url", self.URL, "--viewport", "100x720"], "--viewport"),
            (["--url", self.URL, "--viewport", "wide"], "--viewport"),
            (["--url", self.URL, "--refresh", "5"], "--refresh"),
        ]
        for extra, reason in cases:
            with self.subTest(extra=extra):
                code, _, err = self.run_cli("claim", "x", "--class", "attention",
                                            "--title", "t", "--author", "ann@a", *extra)
                self.assertEqual(code, 1)
                self.assertIn(reason, err)
                self.assertFalse(os.path.exists(self.pane_dir("x")))

    def test_usage_errors_exit_2(self):
        for extra, reason in ((["--theme", "dark", self.page], "need --url"),
                              ([], "pass pane.html"),
                              (["--url", self.URL, self.page], "not both"),
                              # A pane is one band (ADR-0020): the flag is gone.
                              (["--url", self.URL, "--screens", "1"], "unrecognized arguments")):
            with self.subTest(extra=extra):
                err = io.StringIO()   # main() directly: run_cli's own buffer dies with SystemExit
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                    pane.main(["--bus", self.bus, "claim", "x", "--class", "attention",
                               "--title", "t", "--author", "ann@a", *extra], now=T0)
                self.assertEqual(cm.exception.code, 2)
                self.assertIn(reason, err.getvalue())
                self.assertFalse(os.path.exists(self.pane_dir("x")))

    def test_boundaries_match_the_compositor(self):
        # The rules are mirrored from compositor/rubric.py's parse_source: every
        # case here must get the same verdict from both, so neither can drift.
        ok = [{"viewport": "240x240"}, {"viewport": "3840x3840"}, {"refresh": 10},
              {"theme": "light"}]
        bad = [{"viewport": "239x720"}, {"viewport": "1280x3841"}, {"refresh": 9.5}]
        for kw, accepted in [(k, True) for k in ok] + [(k, False) for k in bad]:
            with self.subTest(kw=kw):
                try:
                    source = pane.link_source(self.URL, **kw)
                except pane.Refused:
                    source = None
                self.assertEqual(source is not None, accepted)
                # what the compositor would make of the same request
                raw = {"url": self.URL}
                for k, v in kw.items():
                    if k == "viewport":
                        raw["viewport"] = [int(n) for n in v.split("x")]
                    else:
                        raw[{"refresh": "refresh_s"}.get(k, k)] = v
                try:
                    rubric.parse_source(raw)
                    compositor_accepts = True
                except rubric.Malformed:
                    compositor_accepts = False
                self.assertEqual(compositor_accepts, accepted)

    def test_secret_bearing_urls_match_the_compositor(self):
        cases = [("https://x.test/d?token=abc", False),
                 ("https://s3.test/o?X-Amz-Signature=f00&X-Amz-Credential=a", False),
                 ("https://x.test/cb#access_token=abc", False),
                 ("https://x.test/s?sig=abc", False),
                 ("https://github.com/pulls?q=is%3Apr+author%3Acpitzi", True),
                 ("https://x.test/a#section-2", True)]
        for url, accepted in cases:
            with self.subTest(url=url):
                try:
                    pane.link_source(url)
                    ours = True
                except pane.Refused:
                    ours = False
                try:
                    rubric.parse_source({"url": url})
                    theirs = True
                except rubric.Malformed:
                    theirs = False
                self.assertEqual((ours, theirs), (accepted, accepted))

    def test_ls_and_release_a_link_pane(self):
        self.link()
        code, out, _ = self.run_cli("ls")
        row = next(l for l in out.splitlines() if l.startswith("pr-93"))
        self.assertIn("attention", row)
        self.assertTrue(row.endswith("2026-10-07T16:00:00Z"))
        self.assertEqual(self.run_cli("release", "pr-93", "--author", "ann@a")[0], 0)
        self.assertFalse(os.path.exists(self.pane_dir("pr-93")))

    def test_ls_marks_a_string_source_malformed(self):
        os.makedirs(self.pane_dir("odd"))
        with open(os.path.join(self.pane_dir("odd"), "manifest.json"), "w") as f:
            json.dump({"class": "attention", "title": "t", "created": pane.iso(T0),
                       "ttl_minutes": 60, "author": "ann@a", "source": "https://x.test/"}, f)
        rows = {l.split()[0]: l for l in self.run_cli("ls")[1].splitlines()}
        self.assertTrue(rows["odd"].endswith("malformed"))

    def test_reclaiming_a_page_pane_as_a_link_drops_the_page(self):
        self.claim("pr-93")
        self.assertIn("pane.html", os.listdir(self.pane_dir("pr-93")))
        self.assertEqual(self.link()[0], 0)
        self.assertEqual(os.listdir(self.pane_dir("pr-93")), ["manifest.json"])

    def test_renew_keeps_the_source(self):
        self.link()
        code, _, _ = self.run_cli("renew", "pr-93", "--author", "ann@a",
                                  now=T0 + timedelta(minutes=5))
        self.assertEqual(code, 0)
        self.assertEqual(self.manifest("pr-93")["source"], {"url": self.URL})
        self.assertEqual(self.manifest("pr-93")["created"], "2026-10-07T12:05:00Z")

    def test_another_authors_pane_cannot_become_a_link(self):
        self.claim("pr-93", "bob@b")
        code, _, err = self.link()
        self.assertEqual(code, 1)
        self.assertIn("belongs to bob@b", err)


class LsTests(PaneCase):
    def test_empty_bus(self):
        code, out, _ = self.run_cli("ls")
        self.assertEqual(code, 0)
        self.assertIn("(no panes)", out)
        self.assertIn("current: unavailable", out)

    def test_every_state(self):
        self.claim("live-one", "ann@a")
        self.run_cli("claim", "old", "--class", "focus", "--title", "t",
                     "--author", "bob@b", self.page,
                     now=T0 - timedelta(minutes=30))
        os.makedirs(self.pane_dir("half"))
        with open(os.path.join(self.pane_dir("half"), "pane.html"), "w") as f:
            f.write(PAGE)
        os.makedirs(self.pane_dir("mid-write"))
        for name in ("pane.html", "manifest.json.partial"):
            with open(os.path.join(self.pane_dir("mid-write"), name),
                      "w") as f:
                f.write("x")
        os.makedirs(self.pane_dir("junk"))
        for name in ("pane.html", "manifest.json"):
            with open(os.path.join(self.pane_dir("junk"), name), "w") as f:
                f.write("{" if name == "manifest.json" else PAGE)
        os.makedirs(self.pane_dir("badfield"))
        with open(os.path.join(self.pane_dir("badfield"), "pane.html"),
                  "w") as f:
            f.write(PAGE)
        with open(os.path.join(self.pane_dir("badfield"), "manifest.json"),
                  "w") as f:
            json.dump({"class": "nope", "title": "t", "created": "x",
                       "ttl_minutes": 1, "author": "a"}, f)
        os.makedirs(self.pane_dir("badorigin"))
        with open(os.path.join(self.pane_dir("badorigin"), "pane.html"),
                  "w") as f:
            f.write(PAGE)
        with open(os.path.join(self.pane_dir("badorigin"), "manifest.json"),
                  "w") as f:
            json.dump({"class": "focus", "title": "t", "created": pane.iso(T0),
                       "ttl_minutes": 1, "author": "a", "origin": None}, f)
        os.makedirs(self.pane_dir("link"))
        with open(os.path.join(self.pane_dir("link"), "manifest.json"),
                  "w") as f:
            json.dump({"class": "attention", "title": "t", "created": pane.iso(T0),
                       "ttl_minutes": 60, "author": "cat@c",
                       "source": {"url": "https://example.test/pr/1"}}, f)
        os.makedirs(self.pane_dir("nullsrc"))
        with open(os.path.join(self.pane_dir("nullsrc"), "manifest.json"),
                  "w") as f:
            json.dump({"class": "attention", "title": "t", "created": pane.iso(T0),
                       "ttl_minutes": 60, "author": "dan@d", "source": None}, f)
        os.makedirs(self.pane_dir("lonely"))
        with open(os.path.join(self.pane_dir("lonely"), "manifest.json"),
                  "w") as f:
            f.write("{")
        with open(os.path.join(self.bus, "current.json"), "w") as f:
            json.dump({"pane": "live-one", "class": "attention",
                       "url": "http://pub.lan/viewport/panes/live-one/"
                              "pane.html", "fallback": None}, f)

        code, out, _ = self.run_cli("ls")
        self.assertEqual(code, 0)
        rows = {l.split()[0]: l for l in out.splitlines()}
        self.assertIn("2026-10-07T16:00:00Z", rows["live-one"])
        self.assertIn("attention", rows["live-one"])
        self.assertIn("operator", rows["live-one"])
        self.assertIn("ann@a", rows["live-one"])
        self.assertTrue(rows["old"].endswith("expired"))
        self.assertTrue(rows["half"].endswith("partial"))
        self.assertTrue(rows["mid-write"].endswith("partial"))
        self.assertTrue(rows["junk"].endswith("malformed"))
        self.assertTrue(rows["badfield"].endswith("malformed"))
        self.assertTrue(rows["badorigin"].endswith("malformed"))
        self.assertIn("cat@c", rows["link"])       # a link pane needs no pane.html
        self.assertTrue(rows["link"].endswith("2026-10-07T13:00:00Z"))
        self.assertTrue(rows["lonely"].endswith("partial"))
        self.assertTrue(rows["nullsrc"].endswith("malformed"))
        self.assertIn("current: live-one (attention)", out)

    def test_fallback_pointer(self):
        with open(os.path.join(self.bus, "current.json"), "w") as f:
            json.dump({"pane": None, "fallback": "briefing",
                       "url": "http://pub.lan/brief/"}, f)
        self.assertIn("current: fallback briefing", self.run_cli("ls")[1])


if __name__ == "__main__":
    unittest.main()
