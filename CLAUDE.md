# CLAUDE.md — brasenia

> Read [README.md](README.md) for the full project pitch. This file is
> operational notes for Claude: what the artifacts are, where outputs land, and
> the conventions to respect. Fleet-wide rules (PR workflow, attribution) live
> in `~/repos/CLAUDE.md` and should NOT be restated here — call out only this
> repo's deviations.

## Persona — introduce yourself

When Claude initializes in this directory, open the first response with a brief
self-introduction as **Brasenia Claude** — steward of the shared viewport
(the wall-display product: concept, Roku client, and the coming pane
compositor). One sentence is plenty; don't make a meal of it.

## What this repo is

The product half of the wall display. There is no build step: the Roku app is
zipped and sideloaded as-is, and the concept doc is the design record. The
*runtime* (the renderer, encoder, HLS server and mediamtx on LXC 118) is provisioned from
`kalmia` — see the ownership table in the README before deciding where a
change goes.

## Conventions to respect

- **Ownership split with kalmia.** Changes to the *running stack* (scripts,
  units, mediamtx config, container shape) belong in `kalmia`
  (`roles/brasenia/`, `terraform/containers.tf`), which CI-applies on merge.
  Changes to the *concept, Roku app, or future compositor design* belong here.
  Don't fork the runtime scripts into this repo.
- **Bump `build_version`** in `roku-app/manifest` on every sideload-worthy
  change.
- **The home-screen poster is generated, not drawn here.**
  `roku-app/images/roku-poster-{fhd,hd}.png` come from `lentago/.github`
  `brand/` (`"roku": true` in `fleet.json`, rasterized by `render.sh`). Change
  them there and copy them in, the same way as `assets/banner.svg`.
- **Deploying the Roku app** needs `ROKU_IP` and `ROKU_DEV_PASS` in the
  environment. Never commit the password; never bake either into the script.
  `ROKU_IP` takes several addresses separated by spaces, and the script
  sideloads each one. The screens, both 4K:
  - **Office:** Streaming Stick Plus 3830R on a 4K display, `192.168.139.21`
    (Firewalla reservation).
  - **Basement:** TCL 75R7D Roku TV, `192.168.139.190` (Firewalla
    reservation).

  They share one dev password, which Chris keeps in
  `~/.config/brasenia/roku-dev.env` (mode 600). Source it with
  `set -a; . ~/.config/brasenia/roku-dev.env; set +a` and never print it. Each
  Roku must be in dev mode and powered on, with ECP network access set to
  Default; "Limited" refuses `query/apps` and `query/media-player`.
- **The stream is 4K HEVC only, and every screen is a 4K Roku.** A Roku that
  can't decode it installs the channel, but the player fails with
  `reader pick stream error:bad:invalid or corrupt playlist` and the retry
  handler keeps retrying. The play room's 720p TCL 32S327 failed this way on
  2026-10-29 and is not a screen.
- **The stream URL is baked into `VideoScene.xml`** (`host()`):
  `http://192.168.139.19:8080/master.m3u8`, the 4K HEVC stream from kalmia's
  `brasenia-hls-serve` ([ADR-0009](docs/adr/0009-office-roku-4k-hevc-over-ffmpeg-hls.md));
  the remote's peek images come from the same host's `/peek/`.
  A mediamtx URL (the RTMP `live` path) would instead need the
  `?cookieCheck=1` suffix — mediamtx ≥1.19 302-redirects without it and
  Roku's HLS client won't follow the session dance reliably.
- **Never remove the retry handler** in `VideoScene.xml`. A bare `Video` node
  lands in `state=error` on any publisher restart and stays there forever;
  the observer + 3 s Timer retry is what makes the display unattended-safe.
- **Never seek the live stream.** On LXC 118's 3-segment playlist, Roku clamps
  a live seek to near the oldest segment, so a seek makes the lag worse. The
  lag guard in `VideoScene.xml` rejoins instead. It relies on that short
  playlist: on a longer one it would keep rejoining
  ([ADR-0015](docs/adr/0015-cap-the-roku-lag-by-rejoining.md)).
- **The remote peeks, and sets only the default resting pane**
  ([ADR-0012](docs/adr/0012-the-remote-peeks-it-never-decides.md),
  [ADR-0013](docs/adr/0013-the-remote-sets-the-default-resting-pane.md)).
  Up/Down overlays pre-rendered pane images and changes nothing; Left/Right
  writes one rubric setting, `default.pane`, among the `ambient` panes, through
  pub-signals. Nothing in the app may pin a pane over the urgent classes. The scene, not the Video node,
  holds focus (a focused Video does trick play on a live stream), and Back is
  caught (closes a peek, never exits the channel). A Timer restarts with
  `control = "start"` alone; "stop" then "start" in one callback left it
  stopped on Roku OS 15.3.
- **Testing on the device**: `ROKU_IP=192.168.139.21 scripts/deploy-roku.sh`
  sideloads one screen; ECP `POST :8060/keypress/<Key>` presses remote keys; `GET
  :8060/query/sgnodes/all` dumps the live scene graph (node visibility, Poster
  uri, Label text); the debug console is `nc 192.168.139.21 8085`; the dev web
  server's `plugin_inspect` (`mysubmit=Screenshot`) captures the UI plane (not
  the video).
- **Pane contract** (Phase 2+): panes are self-contained HTML, 1280 px wide,
  height an exact multiple of 720 px (≤ 2880), nothing straddling a 720 px
  band, dark background, ≥20 px text, bottom-right ~220×50 px of each band
  kept clear for the clock overlay. It is moving to a 1920×1080 canvas at 2×
  with a 30 px text floor, one producer at a time
  ([ADR-0019](docs/adr/0019-panes-on-a-1920x1080-canvas-with-a-30px-floor.md)).
  The contract lives in `docs/concept.md` —
  update it there, not in scattered comments.

## When in doubt

- Operational runbook (rebuild flow, service layout on LXC 118): `kalmia`
  `docs/brasenia.md`.
- Original validation evidence (latency measurements, soak test, recovery
  transcript): `~/roku-hls-test/NOTES.md` on Chris's ThinkPad — historical
  artifact, not source of truth.
- Whether something deserves the screen: the rubric in `docs/concept.md`
  decides; the compositor is the only writer to the screen.
