# ADR-0001: Consumer Roku TV + LAN HLS over dedicated decoder hardware

**Status:** Accepted (2026-07-20; reconstructed 2026-08-13)

## Context

The household viewport needed a render path to succeed the retired pve2
`surface`/wall-display concept — concept.md frames the whole project as "the
retired pve2 `surface`/wall-display concept reborn with better bones: the TV
replaces a dedicated display host." Before committing to dedicated HDMI
decoder hardware, the operator needed proof that a $0-incremental-cost path —
a consumer Roku TV playing a LAN-hosted HLS stream via a sideloaded dev
channel — could clear a real acceptance bar.

`docs/roku-hls-test-spec.md` is written as an agent-executable operator spec
("**Receiving agent:** Claude Code, running on a Linux host on the same
routable network as the Roku TV") with a hard bar: glass-to-glass latency
under 30 s (expected 6–15 s), 10+ minutes of stable playback, and automatic
recovery from a publisher restart — all validated **before any hardware
purchase**; decoder-box evaluation is explicitly out of scope for the
validation itself.

`docs/validation-notes-2026-07-20.md` (preserved by PR #3) records the actual
run: mediamtx v1.19.2 (`hlsVariant: mpegts`) + a sideloaded BrightScript dev
channel on a TCL 32S327, measured glass-to-glass latency of 7–17 s (well
under the 30 s bar — the range reflects playlist join depth), a 13.5-minute
clean soak, and automatic ~1 s recovery after a publisher kill (with the v2
retry-handler app; see [ADR-0002](0002-mandatory-client-side-retry-handler.md)).
The notes' own verdict: "the Roku-native HLS path is viable as-is."

## Decision

Adopt the consumer Roku TV + LAN HLS pipeline (ffmpeg → mediamtx → sideloaded
Roku dev channel) as the viewport's display path, validated against the
written acceptance spec before any purchase. The dedicated HDMI decoder box
considered as the fallback was never needed — the Roku-native path passed all
four success criteria in the spec.

## Alternatives

- **Recorded at the time:** dedicated HDMI decoder hardware — the implicit
  fallback the spec's objective was framed against ("... before purchasing
  dedicated HDMI decoder hardware"), explicitly out of scope for the
  validation itself. Rejected because the Roku-native path cleared the bar.
- **Retrospective — not considered at the time:** a Raspberry Pi running a
  browser in kiosk mode over HDMI. Worse — this recreates almost exactly the
  dedicated-display-host pattern the pve2 `surface` retirement was trying to
  get away from: another host to patch, power, and recover after crashes,
  just built from different parts than the original.
- **Retrospective — not considered at the time:** casting (Chromecast-style)
  to the TV. Worse — a cast session is bound to the casting device/app with
  no unattended-recovery story if the caster reboots or the session drops,
  which fails the pipeline's core requirement of surviving a stream restart
  unattended.

## Consequences

- The viewport's display leg has zero incremental hardware cost and no
  dedicated display host to maintain — the TV updates itself and needs only a
  sideloaded dev channel.
- The design is now coupled to Roku's dev-mode sideload model (mandatory
  retry handler, see ADR-0002) and to mediamtx's HLS quirks (the
  `?cookieCheck=1` redirect) rather than to a general-purpose kiosk browser
  that could load any URL directly.
- The decision rests on measured numbers from a single test night on one LAN
  path and one TV model; a materially different deployment (different
  hardware, WAN-hosted stream) should re-run the spec rather than assume the
  same latency margin holds.
