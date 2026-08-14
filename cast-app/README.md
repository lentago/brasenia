# cast-app — Chromecast custom web receiver

Phase A prototype per [ADR-0006](../docs/adr/0006-cast-web-receiver-second-client.md)
and issue #13. This is the **receiver** — the page a Chromecast fetches and
renders when the app launches. There is no sender in this repo: a watchdog
sender that launches/keeps the receiver alive is runtime work owned by
kalmia (lentago/kalmia#99), per the product/runtime split
([ADR-0005](../docs/adr/0005-product-runtime-split-with-kalmia.md)).

Unlike `roku-app/`'s panes, this page is exempt from the pane contract's
self-contained-HTML rule — it's the receiver chrome, not a pane, and loading
the CAF Receiver SDK from Google's CDN is expected and required (Google's
guidance is to always use the gstatic-hosted SDK, never a self-hosted copy).

## What Phase A does

- `index.html` + `receiver.js` load the CAF Receiver SDK from Google's CDN
  and start the receiver context with `disableIdleTimeout: true` — this is a
  signage app with no media session, so the default CAF idle timeout would
  otherwise terminate it after a few minutes with zero senders connected.
- The page displays `http://pub.lan/brief/` full-screen in an iframe, dark
  background.
- If the brief doesn't load within 8s, or the iframe fires a network-level
  error, the page swaps to a built-in dark status card
  ("brief unreachable — retrying…") and retries on a 15s interval — the same
  never-blank-screen discipline as the Roku retry handler
  (`roku-app/components/VideoScene.xml`) and the compositor's fallback
  ladder (`docs/concept.md`).
- Phase B (not this slice, tracked in issue #13) replaces the fixed URL with
  the compositor's current-pane pointer and re-navigates when it changes.

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

## Known risks / open questions (carry into Phase A hosting + watchdog work)

- **Mixed content.** Cast requires the receiver URL to be HTTPS.
  `http://pub.lan/brief/` is plain LAN HTTP. Chrome (which the Chromecast
  runs) blocks or auto-upgrades HTTP iframes embedded in an HTTPS page —
  this will need resolving before Phase A actually renders on-device, either
  via TLS on pub.lan or a same-origin proxy in front of the iframe target.
  Not called out in ADR-0006's trade-off list; flagging here for whoever
  picks up receiver hosting.
- **The iframe `error` event is unreliable for HTTP-level failures**
  (404/500) — most browsers only fire it for network-level failures (DNS,
  connection refused), not bad status codes. The 8s load timeout is the
  primary unreachable signal for that reason; the `error` listener is
  secondary and best-effort.
- Receiver hosting, the watchdog sender, and any systemd/mediamtx-adjacent
  pieces are kalmia's side of this (lentago/kalmia#99) — not part of this
  repo per ADR-0005.
