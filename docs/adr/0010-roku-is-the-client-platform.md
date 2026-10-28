# ADR-0010: Roku is the client platform; the Cast client is retired

**Status:** Accepted (2026-10-28; #61)

## Context

[ADR-0006](0006-cast-web-receiver-second-client.md) (2026-08-14) added a
Chromecast custom web receiver as a second client. It rendered panes natively
as HTML, which gave crisper text and near-instant switching. #12
(2026-10-13) then made the opposite of this ADR the intended end state: retire
the Roku/HLS chain once Cast proved itself. To get there it accepted that the
display would stop working without the internet, because Cast launches its
receiver through Google's cloud.

On 2026-10-28 three things changed:

- The play-room Roku was retired, and a 4K Roku in the office took its place
  ([ADR-0009](0009-office-roku-4k-hevc-over-ffmpeg-hls.md)).
- The Chromecast went offline, and the office Roku became the viewport's only
  screen, following the compositor pointer (#59).
- The Chromecast will not be replaced. It is too expensive, and the house is
  Roku throughout.

Roku also fits Home Assistant. HA's Roku integration speaks ECP, the same
protocol the dev channel is sideloaded and inspected with. With it HA can
power a screen, launch an app (including a sideloaded dev channel) and read
what is playing.

Cast's advantages have also narrowed. The 4K HEVC stream renders panes at
3840×2160, so text is sharp. Switching is still slower (the HLS join takes
about 10–20 s).

## Decision

- **Roku is the client platform.** Every screen is a Roku running the dev
  channel (`roku-app/`), fed by the Roku/HLS adapter on LXC 118.
- **The Cast client is retired.**
  - LXC 118's watchdog is removed (lentago/kalmia#175).
  - pub's receiver publishing goes next (lentago/kalmia#174).
  - `cast-app/` is deleted once that lands.
  - ADR-0006 is superseded, and #12 is closed as not planned.
- **The compositor's output stays a decision.** ADR-0006 reframed the output
  as a pointer each client follows rather than pixels; that survives. Only the
  Cast client goes.
- **Home Assistant is where Roku-side automation goes**, the role the Cast
  watchdog played for the Chromecast: powering screens, and relaunching the
  dev channel after a reboot or an input change. This is future work in
  epigaea (HA config); the product need is recorded here.

## Consequences

- **The display works without the internet again.** The Roku plays a LAN HLS
  stream from LXC 118, which reads only pub.lan. The degraded mode accepted
  on 2026-10-13 no longer applies.
- **Switching stays at HLS speed** (about 10–20 s), and sharp text comes from
  4K HEVC rather than native rendering.
- **Every Roku plays the one stream URL baked into the app.** A second screen
  showing different content would need its own stream, at about 1.4 cores per
  4K encoder. That is a decision for when a second screen arrives.
- **Sideloading is per device.** Each Roku needs dev mode, its own dev
  password and its own sideload. That is fine in one house, but a Lentago
  client deployment would need a distributable (non-certified or beta)
  channel instead.

## Alternatives considered

- **Replace the Chromecast** with a current Google TV device. It costs money,
  and it keeps a second platform alive in a Roku household.
- **Keep both clients.** That means two transports, two keep-alive
  mechanisms and two sets of validation, for one screen.
- **Cast as the only client** (#12's end state). It renders natively, but it
  needs the cloud to launch, needs hardware the house no longer has, and
  doesn't fit Home Assistant the way Roku does.
