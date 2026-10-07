# cast-app — Chromecast custom web receiver

Phase B receiver (Phase A behaviour retained as the 404 rule) per [ADR-0006](../docs/adr/0006-cast-web-receiver-second-client.md)
and issue #13. This is the **receiver** — the page a Chromecast fetches and
renders when the app launches. There is no sender in this repo: a watchdog
sender that launches/keeps the receiver alive is runtime work owned by
kalmia (lentago/kalmia#99), per the product/runtime split
([ADR-0005](../docs/adr/0005-product-runtime-split-with-kalmia.md)).

Unlike `roku-app/`'s panes, this page is exempt from the pane contract's
self-contained-HTML rule — it's the receiver chrome, not a pane, and loading
the CAF Receiver SDK from Google's CDN is expected and required (Google's
guidance is to always use the gstatic-hosted SDK, never a self-hosted copy).

## What the receiver does

- `index.html` + `receiver.js` load the CAF Receiver SDK from Google's CDN
  and start the receiver context with `disableIdleTimeout: true` — this is a
  signage app with no media session, so the default CAF idle timeout would
  otherwise terminate it after a few minutes with zero senders connected.
- **Phase B:** the page polls the compositor's pointer,
  `http://pub.lan/viewport/current.json` (schema 1), every 5 s and shows the
  pointer's `url` full-screen in an iframe on a dark background. It navigates
  only when `url` changes; `title` is never displayed (the pane carries its
  own chrome). The pointer contract itself lives in `docs/concept.md`.
- **Pointer unreadable** (network error, non-2xx other than 404, unparsable
  JSON, or `schema` other than 1): the current pane stays up, and after 30 s
  of continuous failure the built-in status card
  ("viewport pointer unreachable — retrying…") replaces it. If nothing has
  loaded yet (first boot), the card shows at once rather than leaving the
  screen dark. Polling continues, and the pane returns as soon as the pointer
  is readable again.
- **Pane fails to load** (pointer readable, pane URL not loaded within 8 s,
  or a network-level iframe error): the status card ("pane unreachable —
  retrying…") is shown and the next 5 s poll re-navigates to the same URL.
  The receiver does not fall back to the brief on its own; the compositor
  decides fallbacks and reports them in the pointer's `fallback` field.
- **404 means Phase A.** If `current.json` returns 404 (no compositor yet, or
  the file was deleted) the receiver loads `http://pub.lan/brief/` exactly as
  Phase A did, so the wall keeps working until the compositor lands. A brief
  that fails to load shows "brief unreachable — retrying…" and is retried on
  the 5 s poll.
- Same never-blank-screen discipline as the Roku retry handler
  (`roku-app/components/VideoScene.xml`) and the compositor's fallback
  ladder (`docs/concept.md`).

## Testing against a hand-written pointer

Put a `current.json` on the share that pub serves at `/viewport/` and point
`url` at any test pane (or any reachable page):

```json
{"schema": 1, "url": "http://pub.lan/viewport/panes/test/pane.html"}
```

(Only `schema` and `url` are read; the other contract fields may be omitted
for a hand test.) Then, with the receiver running on the Chromecast:

- the test pane should appear within 5 s;
- editing `url` should switch panes within 5 s;
- deleting the file (404) should return the receiver to the brief;
- a pointer with `schema: 2`, broken JSON, or a server 500 should show the
  status card after 30 s, and fixing it should recover without a relaunch.

## Registration prerequisites (Cast Developer Console)

One-time setup, done outside this repo by whoever holds the household's
Google account for Cast development (Chris):

1. **Register as a Cast developer** — https://cast.google.com/publish,
   one-time ~$5 fee.
2. **Register the Chromecast's device serial number** for development —
   required to launch unpublished/custom receiver apps on that specific
   device. The serial is on the device or in the Google Home app.
3. **Register a Custom Receiver application**:
   - App type: Custom Receiver
   - Receiver URL: wherever `index.html` ends up hosted over **HTTPS**
     (hosting is a runtime decision, not made here — see Known risks below)
   - This issues an **App ID**, which is not a secret. Fill it into
     `app-config.json` in this directory; it's what a sender uses to launch
     the receiver.

Fill the placeholders in `app-config.json` once the above is done. Never
commit the Google account credentials or Developer Console session — only
the App ID and receiver URL, matching the `deploy-roku.sh` discipline
(`ROKU_IP`/`ROKU_DEV_PASS` never committed).

## Known risks / open questions (carry into hosting + watchdog work)

- **Mixed content — RESOLVED for the unpublished app (2026-08-14).** The
  Cast Developer Console accepted the plain-HTTP LAN receiver URL
  (`http://pub.lan/cast/`) for an unpublished Custom Receiver, so the
  receiver page and the `http://pub.lan/brief/` iframe are same-scheme and
  no mixed-content blocking applies. App ID `83A58DDE` (in
  `app-config.json`); the app stays unpublished by design — it only ever
  launches on the dev-registered household device, same posture as the
  sideloaded Roku dev channel. The original concern returns only if the app
  is ever *published* (publishing requires an HTTPS receiver URL), which
  would mean TLS on pub or a same-origin proxy — deliberately out of scope.
- **The iframe `error` event is unreliable for HTTP-level failures**
  (404/500) — most browsers only fire it for network-level failures (DNS,
  connection refused), not bad status codes. The 8 s load timeout is the
  primary unreachable signal for that reason; the `error` listener is
  secondary and best-effort.
- Receiver hosting, the watchdog sender, and any systemd/mediamtx-adjacent
  pieces are kalmia's side of this (lentago/kalmia#99) — not part of this
  repo per ADR-0005.
