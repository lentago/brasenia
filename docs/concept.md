# brasenia — the Claude-controlled viewport

*Concept v0.1 — drafted 2026-07-20 during the Roku HLS validation session;
this repo is its canonical home. Conceived as `lunaria` (honesty plant,
translucent seed-pod windows) and renamed the same night: Lunaria annua is a
European garden escape, and the Lentago roster is New England natives only.*

Brasenia (watershield) carpets New England ponds with small floating leaves —
little panes resting on the water's surface. **brasenia** is the household's
shared window into what its Claudes are doing: one always-on screen whose
content is chosen by a rubric, not a remote. The morning brief is the resting
surface; higher-value panes (a PR awaiting review, a failing backup, a deploy
in flight) surface above it when they exist and sink back when they expire.

## Why now

The 2026-07-20 Roku HLS validation accidentally built brasenia's proof of
concept: a `frame.png` slot rendered to a live HLS stream that a $0 sideloaded
Roku channel plays 24/7, already carrying the morning brief and, before that,
a Grafana dashboard. Pane switching happened by a human swapping loops.
Brasenia is that last step made autonomous — and it is the retired pve2
`surface`/wall-display concept reborn with better bones: the TV replaces a
dedicated display host, the NAS replaces host-local state, and the transport
already survives restarts (client retry logic proven).

## Core model

Three nouns:

- **Pane** — a self-contained HTML page rendering some activity, authored to
  the band contract (below), plus a small JSON manifest declaring what it is,
  how important it is, and when it stops mattering.
- **Rubric** — the precedence policy: which pane class outranks which, and
  how staleness decays a pane's claim. Deterministic, versioned in the repo —
  not vibes.
- **Compositor** — the only writer to the screen. Collects live panes,
  applies the rubric, renders the winner into the stream. Falls back to the
  briefing; falls back from *that* to a status card if even the briefing is
  missing.

## Architecture

```
 local Claudes (laptop, fleet workers, Career Claude, …)
      │  write pane dirs (write-then-rename, same discipline as claude-jobs)
      ▼
 NAS pane bus   /volume1/lentago/web/viewport/panes/<pane>/
      │           ├── pane.html      (1..4 bands of 1280×720)
      │           └── manifest.json  (class, priority, ttl, created, author)
      ▼
 viewport LXC 118 (pve4; hostname still `lunaria` pre-rename) — compositor loop:
      1. scan manifests → drop expired → rank via rubric
      2. shoot winner's pane.html (headless chromium, throwaway profile)
      3. slice into 720-bands → rotate through frame.png
      4. ffmpeg (image2pipe → H.264+AAC) → RTSP → mediamtx → HLS :8888
      ▼
 Roku dev channel (roku-app/ in this repo — auto-retry Video node)
      → 32" play-room TV (720p native)
```

The bus is plain files on the share every host already mounts — no broker, no
daemon on the NAS, browsable at `http://pub.lan/viewport/` for free debugging.
Pub stays the *publisher* (Drive → web, credentials live only there); brasenia
is the *renderer* and needs no credentials at all.

## The pane contract

- `pane.html`: self-contained (inline CSS, no external assets/JS), body width
  1280px, height an exact multiple of 720px (≤ 2880). Every 720px band must
  stand alone — nothing straddles a boundary. Dark background, ≥20px body
  text, 24px safe margins, bottom-right ~220×50px of each band kept clear
  (clock overlay is composited there).
- `manifest.json`:

  ```json
  {
    "class": "pr-review",          // rubric key
    "title": "claytonia#67 awaiting review",
    "created": "2026-07-20T21:40:00-04:00",
    "ttl_minutes": 240,             // hard expiry; compositor drops after
    "done_when": "pr-merged",       // optional hint for future auto-expiry
    "author": "repos-claude@thinkpad"
  }
  ```

- Writers use write-then-rename (`pane.html.partial` → `pane.html`), create
  the manifest last, and delete their own pane dir when the activity resolves.
  TTL is the backstop for writers that die without cleaning up.

## Rubric v0

| Priority | Class            | Examples                                | Default TTL |
|---|---|---|---|
| 100 | `alert`        | backup failed, UPS on battery, node down | 60 min |
| 80  | `attention`    | PR awaiting Chris's review, question blocking an agent | 240 min |
| 60  | `activity`     | deploy/migration in flight, fleet working a job | 60 min |
| 40  | `ambient`      | Grafana dashboard, music now-playing      | while fresh |
| 0   | `briefing`     | the morning brief (default resting state) | until next brief |

Ties break by recency. Multiple live panes of the same class rotate. The
briefing never expires — it is the floor, refreshed daily by the existing
routine → Drive → pub chain.

## Governance

A standardized snippet ships in the global `~/.claude/CLAUDE.md` (and the
fleet worker prompts via claytonia): *what* deserves a pane (screen-worthy =
Chris would want to glance up and see it), the pane contract above, and the
rule that Claudes only ever write/remove their **own** pane dirs — the
compositor alone decides what shows. Same shape as the existing pub.lan
drop-folder and bullpen-dispatch instructions: capability documented once,
usable by every session.

## Migration path

- **Phase 0 (done 2026-07-20):** laptop streams brief/Grafana to the TV;
  manual pane switching; publisher on pub.
- **Phase 1 (done 2026-07-20, same night):** streaming stack moved to the
  dedicated viewport LXC (118, pve4, hostname `lunaria`) via kalmia (TF + ansible role); Roku
  app repointed; laptop retired from the loop.
- **Phase 2:** pane bus + manifest + compositor rubric on the viewport LXC; briefing
  and Grafana become the first two pane classes.
- **Phase 3:** governance snippet rolls out to all local Claudes + fleet;
  panes start arriving from real activity (PR queue via the existing
  Infinity/GitHub source, claytonia job status, HA alerts).

## Operational lessons already banked (from the validation night)

- mediamtx ≥1.19 HLS needs `?cookieCheck=1` pre-baked in player URLs.
- Roku's Video node never retries on its own — the app's state-observer +
  3 s Timer retry is mandatory (rejoins ~1 s after a publisher returns).
- Headless-chrome shooters need a throwaway profile per shot (HTTP cache
  served a stale pane) — and slicing needs a background-tolerance mask.
- Kill loop processes by bracketed pattern (`pkill -f 'name[.]sh'`) and never
  in the same command line that spells the plain name; `setsid … &` pgids lie.
- Evening test runs of the cloud brief stamp tomorrow's UTC date — Drive
  name collisions with the real morning run; delete test uploads.

## Open questions

1. Rotation vs. splitting: with 2+ live high-priority panes, rotate the full
   screen (v0) or explore band-level composition (mix panes per band)?
2. Pane render cadence: compositor re-shoots the winner every N minutes —
   is 5 min fresh enough for `activity` panes, or should manifests declare it?
3. Should the TV audio channel ever carry anything (TTS alert chime on
   `alert` panes)? The stream already has an AAC track of silence.
4. Grafana pane: keep the `/render` API approach (no browser needed) as a
   special pane type, or standardize everything through pane.html?
5. ~~Does brasenia eventually own the Roku app?~~ **Answered: yes** — this
   repo ships the BrightScript (`roku-app/`); CI-zipping it is a future nicety.
