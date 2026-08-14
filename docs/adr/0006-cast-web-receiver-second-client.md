# ADR-0006: Chromecast web receiver as a second client; the compositor's output becomes a decision

**Status:** Accepted (2026-08-14)

## Context

A Chromecast joined the household network in August 2026. Its relevant
native capability is that a Cast **Custom Web Receiver** is a managed Chrome
instance on the TV: the device fetches an HTML page and renders it itself,
and the receiver session runs independently of the sender once launched.

That lands squarely on brasenia's luckiest design fact: **panes are already
self-contained HTML** (the pane contract in `../concept.md`). The entire
middle of the Phase 1 chain — headless-Chromium shooter, 720px band
slicer/rotator, ffmpeg H.264 encode, mediamtx, HLS, the `?cookieCheck=1`
workaround — exists only to convert HTML into video because the Roku cannot
render HTML. A device that renders HTML natively makes that conversion
optional for its screen, and buys the two usability wins the video path
cannot deliver: pixel-perfect text (20px body text through x264 at
wall-display bitrates is soft) and near-instant pane switching (versus the
measured 7–17s glass-to-glass).

[ADR-0001](0001-roku-native-hls-over-decoder-hardware.md) retrospectively
rejected "casting (Chromecast-style)" — but what it rejected was casting *a
stream from a caster device*, where the session is tethered to the caster
and dies with it. A custom web receiver is a different shape: the device
fetches and renders content itself, and the open reliability question is
relaunch-after-reboot (a watchdog), not session tether.

The trade-offs against the proven path are real:

- **Cloud dependency.** The Cast leg needs a Google Cast Developer Console
  registration (~$5 one-time), the device's serial registered for
  development, and internet reachability at app launch (Google's app-ID
  lookup). Today's Roku/HLS chain is LAN-self-contained.
- **The unattended story starts at zero soak hours.** A watchdog sender is
  needed to re-launch the receiver after power blips, Chromecast OS updates,
  ambient-mode reclaims, or input changes — the Cast equivalent of the
  mandatory Roku retry handler
  ([ADR-0002](0002-mandatory-client-side-retry-handler.md)), with none of
  its validation evidence yet.
- **Less deterministic rendering.** The server-side shooter guarantees exact
  pixels and is debuggable by inspecting `frame.png`; on-device rendering is
  whatever Chrome version Google shipped, on a consumer SoC.
- **Client fragmentation.** HLS is a dumb pixel bus any video player can
  join (Roku, browser, VLC); native HTML rendering is Cast-specific, and the
  installed Roku TV cannot do it (no webview in SceneGraph).

## Decision

Adopt the Chromecast as a **second client**, not a transport replacement,
per the fleet agnosticism principle (the current implementation is always
the first client, never the product):

1. **The Roku + LAN HLS chain remains the production transport.** ADR-0001
   stands.
2. **The compositor's real output becomes a decision, not pixels**: after
   rubric ranking it publishes a stable current-pane pointer (the winner's
   URL). Client adapters render that decision their own way — the
   shoot→slice→encode→HLS chain is reframed as the *Roku client's adapter*,
   and a Cast web receiver that navigates to the current pane is the second
   client.
3. **The Phase 2 compositor is prototyped against the Cast client first.**
   It is the cheapest proving ground for the rubric/decision loop — no video
   pipeline required, native rendering shows the panes as authored — with a
   watchdog sender on the viewport LXC as its retry-handler analogue.
4. **Acceptance test: adding the Cast client must not touch the Roku
   client.** Retiring the video path for any screen is only on the table
   after the Cast watchdog accumulates unattended soak evidence comparable
   to the 2026-07-20 validation night.

## Alternatives

- **Cast the existing HLS URL to the Default Media Receiver.** Rejected —
  it inherits every cost of the video pipeline (latency, soft text, encoder
  CPU), adds Cast's media CORS requirement on the HLS origin (mediamtx
  `hlsAllowOrigin`) and the default receiver's idle-timeout behavior, and
  exploits nothing the device is natively good at.
- **Replace the Roku/HLS path outright with Cast-native rendering.**
  Rejected for now — it trades LAN self-containment for a Google cloud
  dependency and discards a proven unattended-recovery story for an
  unproven one in a single step.
- **Do nothing until Phase 2 lands on the video path.** Rejected — crisp
  text and instant switching are the product's core glanceability, and the
  Cast client makes the Phase 2 compositor cheaper to prove, not more
  expensive.

## Consequences

- The pane bus + rubric + decision pointer are now formally the product;
  renderers are clients. The pane contract's band constraints (1280×720
  bands, nothing straddling a boundary) remain the portable invariant even
  though the Cast renderer doesn't need them — they are what keeps every
  future client (including the installed Roku) possible.
- Two client classes must be kept alive until one demonstrably retires the
  other; each carries its own recovery mechanism (Roku retry handler; Cast
  watchdog sender).
- The Cast leg introduces external dependencies the Roku leg doesn't have:
  Google console registration, a dev-registered device, and internet at app
  launch. An internet outage degrades the Cast screen while the Roku/HLS
  screen keeps working — one more reason the HLS chain stays production.
- Per the product/runtime split
  ([ADR-0005](0005-product-runtime-split-with-kalmia.md)): this repo owns
  the receiver page and the current-pane pointer contract (client + product
  surface, like `roku-app/`); the watchdog sender, its systemd unit, and
  any mediamtx config changes are runtime and belong in kalmia.
- ADR-0001's retrospective rejection of casting is refined, not overturned:
  sender-tethered casting stays rejected; receiver-native rendering enters
  as a client under the acceptance test above.
