import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from helpers import FIXTURES
from family_brief_producer.__main__ import main

SOURCE = "file://" + os.path.join(FIXTURES, "example", "latest.json")
NOW = "2026-10-25T15:00:00Z"


class OnceTests(unittest.TestCase):
    def run_once(self, webroot):
        with redirect_stdout(StringIO()):
            return main(["--once", "--webroot", webroot, "--source", SOURCE, "--now", NOW])

    def test_success_exits_zero(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.run_once(root), 0)

    def test_failed_cycle_exits_nonzero(self):
        # pane.html is a directory, so publishing the page raises.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "viewport", "panes", "family-today", "pane.html"))
            self.assertEqual(self.run_once(root), 1)


if __name__ == "__main__":
    unittest.main()
