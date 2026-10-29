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


if __name__ == "__main__":
    unittest.main()
