import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from helpers import SLOTS

from grafana_producer import __main__ as cli


class MainTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def run_main(self, *argv, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=True), redirect_stderr(io.StringIO()) as err, \
                mock.patch.object(cli.logging, "basicConfig"):
            try:
                return cli.main(list(argv)), err.getvalue()
            except SystemExit as exc:
                return exc.code, err.getvalue()

    def test_the_stack_url_must_be_plain_https(self):
        for url in ("http://grafana.test", "https://user:pw@grafana.test",
                    "https://grafana.test/?auth=x", "grafana.test"):
            with self.subTest(url=url):
                code, err = self.run_main("--webroot", self.root, "--grafana-url", url,
                                          "--slots", SLOTS, "--token-file", "/nonexistent")
                self.assertEqual(code, 2)
                self.assertIn("plain https://", err)

    def test_the_token_file_defaults_to_the_systemd_credential(self):
        code, err = self.run_main("--webroot", self.root, "--grafana-url", "https://grafana.test",
                                  "--slots", SLOTS)
        self.assertEqual(code, 2)
        self.assertIn("--token-file is required", err)
        with mock.patch.object(cli, "Producer") as producer:
            producer.return_value.cycle.return_value = 0
            code, _ = self.run_main("--webroot", self.root, "--grafana-url", "https://grafana.test",
                                    "--slots", SLOTS, "--once", env={"CREDENTIALS_DIRECTORY": "/run/creds"})
        self.assertEqual(code, 0)
        self.assertEqual(producer.call_args.args[1], "/run/creds/grafana-token")

    def test_a_bad_slot_file_is_a_usage_error(self):
        path = os.path.join(self.root, "slots.json")
        with open(path, "w") as fh:
            fh.write('{"slots": [{"pane": "x"}]}')
        code, err = self.run_main("--webroot", self.root, "--grafana-url", "https://grafana.test",
                                  "--slots", path, "--token-file", "/nonexistent")
        self.assertEqual(code, 2)
        self.assertIn("has no 'uid'", err)

    def test_once_exits_1_when_a_render_failed(self):
        with mock.patch.object(cli, "Producer") as producer:
            producer.return_value.cycle.return_value = 1
            code, _ = self.run_main("--webroot", self.root, "--grafana-url", "https://grafana.test",
                                    "--slots", SLOTS, "--token-file", "/x", "--once")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
