"""A small Grafana render API client: one dashboard as a PNG.

``GET <stack>/render/d/<uid>`` with the token as a bearer header. The token
is never logged or rendered, and redirects are not followed: Grafana answers
a missing or rejected token by sending the browser to its login page, which
would otherwise come back as a 200 with HTML in it.
"""

import struct
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = 90              # the client's wait; RENDER_TIMEOUT_S is the server's
RENDER_TIMEOUT_S = 60
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class GrafanaError(Exception):
    """Any render failure: network, HTTP status, or a body that isn't a PNG.

    ``retry_after`` is the seconds Grafana asked us to wait (HTTP 429's
    ``Retry-After``), or None.
    """

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None     # urllib then raises HTTPError with the 3xx status


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_transport(url, headers, timeout=TIMEOUT_S):
    """GET ``url``; return ``(status, headers, body bytes)``. Raises OSError on network failure."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()) if err.headers else {}, err.read()


def utc_offset(when):
    """Grafana's documented ``tz`` form: ``UTC+HH:MM`` for an aware datetime."""
    minutes = int(when.utcoffset().total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return "UTC%s%02d:%02d" % (sign, abs(minutes) // 60, abs(minutes) % 60)


def render_url(base, slot, local_now):
    """The render URL for ``slot`` (a ``slots.Slot``); ``local_now`` sets ``tz``."""
    width, height = slot.size
    query = [
        ("orgId", str(slot.org_id)),
        ("from", slot.time_from),
        ("to", slot.time_to),
        ("width", str(width)),
        ("height", str(height + slot.crop_px)),
        ("scale", str(slot.scale)),
        ("theme", slot.theme),
        ("kiosk", "1"),
        ("tz", utc_offset(local_now)),
        ("timeout", str(RENDER_TIMEOUT_S)),
    ]
    query += [("var-" + name, value) for name, value in sorted(slot.vars.items())]
    return "%s/render/d/%s?%s" % (base.rstrip("/"), urllib.parse.quote(slot.uid, safe=""),
                                  urllib.parse.urlencode(query))


def png_size(data):
    """``(width, height)`` from a PNG's IHDR chunk, or None when ``data`` isn't a PNG."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def retry_after(headers):
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return max(0, int(value.strip()))
            except ValueError:
                return None     # an HTTP date; the caller's backoff applies
    return None


class Client:
    def __init__(self, base_url, token, transport=urllib_transport):
        self.base = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def render(self, slot, local_now):
        """The slot's dashboard as PNG bytes; raises GrafanaError."""
        headers = {"Authorization": "Bearer " + self.token, "Accept": "image/png",
                   "User-Agent": "brasenia-grafana-producer"}
        try:
            status, resp_headers, body = self.transport(render_url(self.base, slot, local_now),
                                                        headers)
        except OSError as err:
            raise GrafanaError("unreachable (%s)" % err) from None
        if status in (401, 403):
            raise GrafanaError("rejected the token (HTTP %d)" % status)
        if status in (301, 302, 303, 307, 308):
            raise GrafanaError("redirected to a login (HTTP %d): the token is missing or rejected"
                               % status)
        if status == 429:
            raise GrafanaError("is rate limiting renders (HTTP 429)", retry_after(resp_headers))
        if status != 200:
            raise GrafanaError("answered the render with HTTP %d" % status)
        if png_size(body) is None:
            raise GrafanaError("answered the render with something that isn't a PNG")
        return body
