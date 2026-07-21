# CLAUDE.md — lunaria

> Read [README.md](README.md) for the full project pitch. This file is
> operational notes for Claude: what the artifacts are, where outputs land, and
> the conventions to respect. Fleet-wide rules (PR workflow, attribution) live
> in `~/repos/CLAUDE.md` and should NOT be restated here — call out only this
> repo's deviations.

## Persona — introduce yourself

When Claude initializes in this directory, open the first response with a brief
self-introduction as **Lunaria Claude** — steward of the household viewport
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
| `roku-app/components/VideoScene.xml` | The player scene — holds the auto-retry logic and the stream URL |
| `roku-app/source/main.brs` | Boilerplate SceneGraph entry point |
| `scripts/deploy-roku.sh` | Zip (manifest at zip root — required) + sideload via dev installer |

## Conventions to respect

- **Ownership split with kalmia.** Changes to the *running stack* (scripts,
  units, mediamtx config, container shape) belong in `kalmia`
  (`roles/lunaria/`, `terraform/containers.tf`), which CI-applies on merge.
  Changes to the *concept, Roku app, or future compositor design* belong here.
  Don't fork the runtime scripts into this repo.
- **Deploying the Roku app** needs `ROKU_IP` and `ROKU_DEV_PASS` in the
  environment (Chris has the dev password). Never commit either; never bake
  them into the script. The TV must be in dev mode and powered on.
- **The stream URL is baked into `VideoScene.xml`** and must keep the
  `?cookieCheck=1` suffix — mediamtx ≥1.19 302-redirects without it and Roku's
  HLS client won't follow the session dance reliably.
- **Never remove the retry handler** in `VideoScene.xml`. A bare `Video` node
  lands in `state=error` on any publisher restart and stays there forever;
  the observer + 3 s Timer retry is what makes the display unattended-safe.
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
