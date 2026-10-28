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
*runtime* (mediamtx + shooter/rotator/encoder on LXC 118) is provisioned from
`kalmia` — see the ownership table in the README before deciding where a
change goes.

## Artifacts / layout

| Path | Purpose |
|---|---|
| `docs/concept.md` | Product concept: pane/rubric/compositor model, pane contract, rubric v0, phases |
| `roku-app/manifest` | Channel identity; bump `build_version` on every sideload-worthy change |
| `roku-app/components/VideoScene.xml` | The player scene — holds the auto-retry logic, the LXC 118 host (stream and peek), and the remote's peek (Up/Down, Back) |
| `roku-app/components/LineupTask.xml` | Task that polls LXC 118's `/peek/index.json` for the remote's peek (no network I/O on the render thread) |
| `roku-app/source/main.brs` | Boilerplate SceneGraph entry point |
| `compositor/` | Phase 2 compositor (stdlib Python 3.11+): `rubric.decide()` is the pure ranking function, `bus.py` the filesystem half; runs on pub, unit runtime in kalmia |
| `bin/pane` | Claim/renew/release/ls a pane on the viewport bus (stdlib Python 3.11+); governance text in `docs/claiming-the-display.md` |
| `scripts/deploy-roku.sh` | Zip (manifest at zip root — required) + sideload via dev installer |

## Conventions to respect

- **Ownership split with kalmia.** Changes to the *running stack* (scripts,
  units, mediamtx config, container shape) belong in `kalmia`
  (`roles/lunaria/`, `terraform/containers.tf`), which CI-applies on merge.
  Changes to the *concept, Roku app, or future compositor design* belong here.
  Don't fork the runtime scripts into this repo. (kalmia's role and the
  container hostname keep the pre-rename `lunaria` name until kalmia#63
  lands — don't "fix" stray `lunaria` strings there from this repo; that
  issue owns the runtime rename per the fleet rename discipline.)
- **Deploying the Roku app** needs `ROKU_IP` and `ROKU_DEV_PASS` in the
  environment. Never commit either; never bake them into the script. The
  office Roku is `192.168.139.21`; Chris keeps its dev password in
  `~/.config/brasenia/roku-dev.env` (mode 600) — source it with
  `set -a; . ~/.config/brasenia/roku-dev.env; set +a` and never print it. The
  Roku must be in dev mode and powered on.
- **The stream URL is baked into `VideoScene.xml`** (`host()`):
  `http://192.168.139.19:8080/master.m3u8`, the 4K HEVC stream from kalmia's
  `lunaria-hls-serve` ([ADR-0009](docs/adr/0009-office-roku-4k-hevc-over-ffmpeg-hls.md));
  the remote's peek images come from the same host's `/peek/`.
  A mediamtx URL (the RTMP `live` path) would instead need the
  `?cookieCheck=1` suffix — mediamtx ≥1.19 302-redirects without it and
  Roku's HLS client won't follow the session dance reliably.
- **Never remove the retry handler** in `VideoScene.xml`. A bare `Video` node
  lands in `state=error` on any publisher restart and stays there forever;
  the observer + 3 s Timer retry is what makes the display unattended-safe.
- **The remote peeks; it never decides** ([ADR-0012](docs/adr/0012-the-remote-peeks-it-never-decides.md)).
  Up/Down overlays pre-rendered pane images; nothing the app does may change
  the stream or the compositor's decision. The scene, not the Video node,
  holds focus (a focused Video does trick play on a live stream), and Back is
  caught (closes a peek, never exits the channel). A Timer restarts with
  `control = "start"` alone; "stop" then "start" in one callback left it
  stopped on Roku OS 15.3.
- **Testing on the device**: `ROKU_IP=192.168.139.21 scripts/deploy-roku.sh`
  sideloads; ECP `POST :8060/keypress/<Key>` presses remote keys; `GET
  :8060/query/sgnodes/all` dumps the live scene graph (node visibility, Poster
  uri, Label text); the debug console is `nc 192.168.139.21 8085`; the dev web
  server's `plugin_inspect` (`mysubmit=Screenshot`) captures the UI plane (not
  the video).
- **Pane contract** (Phase 2+): panes are self-contained HTML, 1280 px wide,
  height an exact multiple of 720 px (≤ 2880), nothing straddling a 720 px
  band, dark background, ≥20 px text, bottom-right ~220×50 px of each band
  kept clear for the clock overlay. The contract lives in `docs/concept.md` —
  update it there, not in scattered comments.

## When in doubt

- Operational runbook (rebuild flow, service layout on LXC 118): `kalmia`
  `docs/lunaria.md`.
- Original validation evidence (latency measurements, soak test, recovery
  transcript): `~/roku-hls-test/NOTES.md` on Chris's ThinkPad — historical
  artifact, not source of truth.
- Whether something deserves the screen: the rubric in `docs/concept.md`
  decides; the compositor is the only writer to the screen.
