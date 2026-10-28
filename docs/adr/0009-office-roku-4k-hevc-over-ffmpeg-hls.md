# ADR-0009: The office Roku plays 4K HEVC from ffmpeg-written HLS; the play-room Roku is retired

**Status:** Accepted (2026-10-28; runtime in kalmia#167, product in #52).
Amended the same day (#59): the office follows the pointer; see the end.

## Context

The play-room Roku (a TCL 32S327, a 720p panel) was factory reset on
2026-10-28 and is retired as a client. A Roku Streaming Stick Plus (3830R) in
the office replaces it, on a 4K display: `roDeviceInfo.GetVideoMode()`
reports `2160p60b10`. The office shows the Family Brief pane
(`viewport/panes/family-today/`), not whatever the compositor picks.

Panes are laid out in 1280×720 CSS pixels (the pane contract). Until now the
Roku/HLS adapter on LXC 118 shot them at 1:1, encoded H.264 at 10 fps, and
pushed the stream into mediamtx, whose `mpegts` HLS variant the Roku played
([ADR-0001](0001-roku-native-hls-over-decoder-hardware.md)).

A bench on 2026-10-28, on LXC 118 and the office Roku, found:

- Roku plays H.264 only up to 1080p, so 4K means HEVC (or VP9).
- mediamtx v1.19.2 cannot deliver HEVC to a Roku. Its `mpegts` HLS variant is
  H.264-only (`the MPEG-TS variant of HLS supports H264 video only`). Its
  `fmp4` variant serves HEVC but declares `#EXT-X-VERSION:10`, which the Roku
  rejects (`HLS playlist unsupported version`). The variant is a server-wide
  setting.
- ffmpeg's own HLS muxer, writing HEVC into MPEG-TS segments (playlist
  version 6), plays on the Roku at 3840×2160, and the retry handler
  ([ADR-0002](0002-mandatory-client-side-retry-handler.md)) recovers it from
  an encoder restart.
- Chromium's device scale factor renders an unchanged 1280×720 pane at a
  true 3840×2160.
- libx265 (`ultrafast`, `zerolatency`) at 4K managed about 8 fps on LXC 118's
  two cores, short of 10. At 5 fps it uses about 1.4 cores and 620 MB.

## Decision

- **Scale, don't re-lay-out.** The office pane is shot at 3× device scale
  (3840×2160). The pane contract is unchanged: producers keep designing in
  1280×720 CSS pixels, and any pane renders at 4K without changes.
- **HEVC at 5 fps.** The burned-in clock ticks once a second, so 5 fps loses
  nothing visible. GOP and segment are both 2 s; the target bitrate is
  6 Mbps.
- **ffmpeg writes the HLS; mediamtx leaves the display path.** Segments and a
  master playlist (declaring `RESOLUTION` and `CODECS`) go to tmpfs on
  LXC 118 and are served by a small stdlib HTTP server on `:8080`. The
  playlist never carries `#EXT-X-ENDLIST`, and segment numbers come from the
  clock, so an encoder restart never leaves a finished playlist or a
  sequence that runs backwards.
- **The office is pinned** *(superseded by the amendment below)*. The adapter shows the Family Brief pane and does
  not read the viewport pointer. Following the pointer stays a one-setting
  change in kalmia (`lunaria_pin_url`).
- **LXC 118 grows to 4 cores and 4 GB** for the encoder and Chromium's 3×
  shots.

## Consequences

- The Roku/HLS chain lives on, now for the office rather than the wall.
  #12 planned to turn the chain down once Cast proved itself; that plan now
  has to leave the office stream running.
- The office display is LAN-self-contained (no cloud launch step), unlike the
  Cast path. During an internet outage it keeps showing the last Family Brief
  pub has.
- *(Superseded by the amendment below.)* The rubric does not govern the office screen. A client adapter can pin to
  one pane; the compositor's decision still governs the clients that follow
  the pointer.
- mediamtx keeps only the RTMP `live` ingest path
  ([ADR-0007](0007-live-rtmp-ingest-generic-path.md)). Its `fallback: /board`
  now has no publisher to fall back to, and an H.264 `live` stream is not the
  4K HEVC stream the office plays. What live ingest becomes is #17's
  question.
- About 1.4 cores of pve4 are spent continuously on the encoder.

## Alternatives considered

- **H.264 at 1080p through the existing mediamtx path.** It would need no
  new server or codec, but 1080p is the Roku's H.264 ceiling and the
  display is 4K, which was the point of the change.
- **mediamtx's `fmp4` HLS variant.** It carries HEVC, but the Roku rejects
  its playlist version. A second mediamtx instance does not help, because
  both variants fail for this client.
- **10 fps.** Does not fit two cores, and it buys nothing visible on a
  static page with a once-a-second clock.
- **The Intel iGPU (UHD 630) encoding HEVC.** Near-zero CPU, but it needs
  `/dev/dri` passed into the unprivileged LXC, which complicates the
  API-token Terraform apply that creates it. Held in reserve if the CPU cost
  becomes a problem.
- **Rendering on the Roku itself** (a SceneGraph Poster of a PNG). The
  Roku's UI plane tops out at 1080p; only the video plane reaches 4K.

## Amendment: the office follows the pointer (2026-10-28, #59)

The Chromecast ([ADR-0006](0006-cast-web-receiver-second-client.md)'s Cast
client) went offline the same day, which left the office Roku as the
viewport's only screen. The adapter now follows the compositor's pointer
like any client, so the rubric governs the office screen. Pull-request,
pipeline and alert panes reach it, and the Family Brief pane is its resting
surface. To keep the desk edition (#56), the shooter prefers a pane's
`detail.html` when the pane offers one beside `pane.html`, and panes without
one show `pane.html` at 3×. Pinning stays a one-setting change in kalmia
(`lunaria_pin_url`); the preference is `lunaria_prefer_rendition`.
