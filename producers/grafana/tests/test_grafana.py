import http.server
import threading
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from helpers import STACK, TOKEN, FakeGrafana, make_png

from grafana_producer import grafana
from grafana_producer.grafana import Client, GrafanaError
from grafana_producer.slots import parse

NY = ZoneInfo("America/New_York")


def slot(**fields):
    raw = {"pane": "grafana-x", "uid": "firewalla-infra-health", "title": "X"}
    raw.update(fields)
    return parse({"slots": [raw]})[0]


class RenderUrlTest(unittest.TestCase):

    def test_the_url_asks_for_the_slot_at_its_size_plus_the_crop(self):
        when = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc).astimezone(NY)
        url = grafana.render_url(STACK + "/", slot(vars={"host": "pve4"}), when)
        self.assertEqual(url, STACK + "/render/d/firewalla-infra-health?orgId=1&from=now-6h&to=now"
                         "&width=1232&height=650&scale=1&theme=dark&kiosk=1&tz=UTC-04%3A00"
                         "&timeout=60&var-host=pve4")

    def test_tz_follows_daylight_saving(self):
        winter = datetime(2026, 12, 1, 12, tzinfo=timezone.utc).astimezone(NY)
        self.assertEqual(grafana.utc_offset(winter), "UTC-05:00")
        self.assertEqual(grafana.utc_offset(datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata"))),
                         "UTC+05:30")


class ClientTest(unittest.TestCase):

    def setUp(self):
        self.fake = FakeGrafana()
        self.now = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc).astimezone(NY)

    def render(self, token=TOKEN, **fields):
        return Client(STACK, token, self.fake).render(slot(**fields), self.now)

    def test_a_render_is_a_png_of_the_asked_for_size(self):
        png = self.render(scale=2)
        self.assertEqual(grafana.png_size(png), (2464, 1300))

    def test_a_rejected_token_is_a_redirect_to_the_login_and_is_not_followed(self):
        with self.assertRaisesRegex(GrafanaError, "login") as cm:
            self.render(token="revoked")
        self.assertNotIn("revoked", str(cm.exception))
        self.fake.status = 401
        with self.assertRaisesRegex(GrafanaError, "rejected the token"):
            self.render()

    def test_429_carries_retry_after(self):
        self.fake.status, self.fake.headers = 429, {"retry-after": "120"}
        with self.assertRaises(GrafanaError) as cm:
            self.render()
        self.assertEqual(cm.exception.retry_after, 120)
        self.fake.headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        with self.assertRaises(GrafanaError) as cm:
            self.render()
        self.assertIsNone(cm.exception.retry_after)

    def test_other_failures(self):
        self.fake.status = 500
        with self.assertRaisesRegex(GrafanaError, "HTTP 500"):
            self.render()
        self.fake.status, self.fake.body = 200, b"<!DOCTYPE html><title>Grafana</title>"
        with self.assertRaisesRegex(GrafanaError, "isn't a PNG"):
            self.render()
        self.fake.body, self.fake.down = None, True
        with self.assertRaisesRegex(GrafanaError, "unreachable"):
            self.render()

    def test_the_token_goes_only_in_the_authorization_header(self):
        seen = {}

        def transport(url, headers, timeout=None):
            seen.update(url=url, headers=headers)
            return 200, {}, make_png(4, 4)

        Client(STACK, TOKEN, transport).render(slot(), self.now)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, seen["url"])

    def test_png_size(self):
        self.assertEqual(grafana.png_size(make_png(7, 3)), (7, 3))
        self.assertIsNone(grafana.png_size(b"<html>"))


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/render/d/redirect":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        elif path == "/login":
            body = b"<html>login</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.server.login_hits += 1
        elif path == "/render/d/slow":
            self.server.release.wait(5)
        elif path == "/render/d/limited":
            self.send_response(429)
            self.send_header("Retry-After", "42")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        elif path == "/render/d/denied":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            body = make_png(4, 4)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class RealTransportTest(unittest.TestCase):
    """The urllib transport against a local http.server: no mock at the Client seam."""

    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.login_hits = 0
        self.server.release = threading.Event()
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.release.set)
        self.now = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc).astimezone(NY)

    def render(self, uid, token=TOKEN, transport=grafana.urllib_transport):
        return Client(self.base, token, transport).render(slot(uid=uid), self.now)

    def test_a_png_comes_back(self):
        self.assertEqual(grafana.png_size(self.render("ok")), (4, 4))

    def test_a_redirect_to_the_login_is_an_error_and_is_not_followed(self):
        with self.assertRaisesRegex(GrafanaError, "redirected to a login"):
            self.render("redirect")
        self.assertEqual(self.server.login_hits, 0)

    def test_http_errors_map_to_grafana_errors(self):
        with self.assertRaisesRegex(GrafanaError, "rejected the token"):
            self.render("denied")
        with self.assertRaises(GrafanaError) as cm:
            self.render("limited")
        self.assertEqual(cm.exception.retry_after, 42)

    def test_a_server_that_never_answers_times_out(self):
        def short(url, headers, timeout=None):
            return grafana.urllib_transport(url, headers, timeout=0.3)

        with self.assertRaisesRegex(GrafanaError, "unreachable"):
            self.render("slow", transport=short)

    def test_a_token_with_a_newline_never_reaches_the_error(self):
        secret = "sekrit-a\nsekrit-b"
        with self.assertRaises(GrafanaError) as cm:
            self.render("ok", token=secret)
        self.assertNotIn("sekrit", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
