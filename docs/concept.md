# brasenia — the Claude-controlled viewport

*Concept v0.1 — drafted 2026-07-20 during the Roku HLS validation session;
this repo is its canonical home. Conceived as `lunaria` (honesty plant,
translucent seed-pod windows) and renamed the same night: Lunaria annua is a
European garden escape, and the Lentago roster is New England natives only.*

*Amended 2026-08-14: the architecture gains a second client branch — a
Chromecast custom web receiver rendering panes natively — and the
compositor's output is reframed as a decision, not pixels
([ADR-0006](adr/0006-cast-web-receiver-second-client.md)).*

*Amended 2026-10-07: rubric v1 (adds `focus`, an `origin` tie-break and
rotation by dwell) replaces rubric v0, the bus contracts are written down as
[Contracts v1](#contracts-v1), and the compositor moves to pub (LXC 114)
([#27](https://github.com/lentago/brasenia/issues/27)).*

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
      │           └── manifest.json  (class, ttl, created, author, origin)
      ▼
 pub (LXC 114, mounts and serves the share) — compositor:
      1. scan manifests → drop expired → rank via rubric
      2. publish the decision — viewport/current.json, the pointer
         every client follows (http://pub.lan/viewport/current.json)
      ▼
 client adapters — one per screen; adding one must not touch the others
      │
      ├─ Roku/HLS adapter (first client — production)
      │    3. shoot winner's pane.html (headless chromium, throwaway profile)
      │    4. slice into 720-bands → rotate through frame.png
      │    5. ffmpeg (image2pipe → H.264+AAC) → RTSP → mediamtx → HLS :8888
      │    ▼
      │  Roku dev channel (roku-app/ in this repo — auto-retry Video node)
      │       → 32" play-room TV (720p native)
      │
      └─ Cast adapter (second client — ADR-0006, prototype)
           3. custom Web Receiver navigates to the current pane and renders
              it natively (pixel-perfect text, ~instant pane switching)
           4. watchdog sender on the LXC re-launches the receiver after
              reboots / OS updates / ambient reclaims
           ▼
         Chromecast → its TV
```

The bus is plain files on the share every host already mounts — no broker, no
daemon on the NAS, browsable at `http://pub.lan/viewport/` for free debugging.
Pub stays the *publisher* (Drive → web, credentials live only there); brasenia
is the *renderer* and needs no credentials at all.

The compositor's real output is the **decision**, not pixels — the
shoot→slice→encode→HLS chain is the *Roku client's adapter*, not the product,
and the Cast web receiver is the second client
([ADR-0006](adr/0006-cast-web-receiver-second-client.md)). The trade is
recorded there: the Cast leg wins on text crispness and switching latency but
depends on Google's cloud at launch and starts with zero unattended soak
hours, so Roku/HLS stays the production transport until the Cast watchdog
earns comparable validation evidence.

**Compositor placement (2026-10-07).** The compositor runs on pub (LXC
114), from the `/srv/brasenia` checkout kalmia already keeps there, because
pub mounts and serves the share and LXC 118 has no NAS mount by design. LXC
118 stays a client adapter: it reads the pointer over HTTP like any other
client. The runtime half (unit, schedule, checkout) is kalmia's
([kalmia#140](https://github.com/lentago/kalmia/issues/140)).

## The pane contract

- `pane.html`: self-contained (inline CSS, no external assets/JS), body width
  1280px, height an exact multiple of 720px (≤ 2880). Every 720px band must
  stand alone — nothing straddles a boundary. Dark background, ≥20px body
  text, 24px safe margins, bottom-right ~220×50px of each band kept clear
  (clock overlay is composited there).
- `manifest.json`: the fields and liveness rule are in
  [Contracts v1](#manifestjson).
- Writers use write-then-rename (`pane.html.partial` → `pane.html`), create
  the manifest last, and delete their own pane dir when the activity resolves.
  TTL is the backstop for writers that die without cleaning up.

## Rubric v1

*Replaces rubric v0 (2026-10-07): adds `focus` at 50, the `origin`
tie-break, and rotation by `dwell_s`.*

| Priority | Class | Default TTL |
|---|---|---|
| 100 | `alert` | 60 min |
| 80 | `attention` | 240 min |
| 70 | `live` | while the publisher is present |
| 60 | `activity` | 60 min |
| 50 | `focus` | 10 min |
| 40 | `ambient` | while fresh |
| 0 | `briefing` | never |

Ranking: priority descending, then `origin` (`operator` before `fleet`), then `created` descending. Panes tied on priority and origin rotate; each shows for its `dwell_s` (default 20 s) before the next. Only the top group rotates; lower groups wait. Fallback ladder: no live pane → the briefing URL (`http://pub.lan/brief/` by default, skipped when its `index.html` is absent under the webroot) → `status.html`, which the compositor writes with the reason.

## Contracts v1

These are the contracts every Phase 2 piece builds to (the compositor, the
Cast client following the pointer, the focus producer, and the session
heartbeat beacon). Other issues and repos quote the parts they need and must
not diverge; change them here. The implementation is
[`compositor/`](../compositor/).

### Paths

| Where | Path |
|---|---|
| NAS share, workstation | `/mnt/lentago/web/viewport/` |
| pub (LXC 114), served by Caddy | `/srv/www/viewport/` |
| URL | `http://pub.lan/viewport/` |

Inside it:

- `panes/<pane>/pane.html` and `panes/<pane>/manifest.json`, one directory per pane. Pane id `[a-z0-9][a-z0-9-]{0,62}`.
- `focus/<host>-<session8>.json`, session beacons, the focus producer's input.
- `current.json`, the compositor's decision (the pointer every client follows).
- `status.html`, the status card the compositor writes as the fallback of last resort.
- `state/`, compositor rotation state.

Writers use write-then-rename for every file (`x.partial` → `x`) and write `manifest.json` last. A writer relinquishes by deleting its own pane directory. The compositor is the only writer of `current.json`, `status.html` and `state/`.

### manifest.json

```json
{
  "schema": 1,
  "class": "focus",
  "title": "brasenia — open pull requests",
  "created": "2026-10-07T12:00:00Z",
  "ttl_minutes": 10,
  "author": "focus-producer@pub",
  "origin": "operator",
  "repo": "lentago/brasenia",
  "dwell_s": 20,
  "done_when": "pr-merged"
}
```

- `class` is one of `alert`, `attention`, `live`, `activity`, `focus`, `ambient`, `briefing`. `title`, `created` (RFC 3339, UTC), `ttl_minutes`, `author` are required.
- `origin` is `operator` or `fleet` (default `fleet`); it is the tie-break within a class.
- `repo` (`owner/name`), `dwell_s` and `done_when` are optional. v1 ignores `done_when`.
- A pane is live when both files exist, neither is a `.partial`, the manifest parses, and `created + ttl_minutes` is in the future.

### current.json (the pointer)

```json
{
  "schema": 1,
  "decided_at": "2026-10-07T12:00:05Z",
  "pane": "focus-lentago-brasenia",
  "url": "http://pub.lan/viewport/panes/focus-lentago-brasenia/pane.html",
  "class": "focus",
  "priority": 50,
  "title": "brasenia — open pull requests",
  "expires_at": "2026-10-07T12:10:00Z",
  "fallback": null,
  "rotation": {"index": 0, "of": 2, "dwell_s": 20}
}
```

- `pane` is null and `fallback` is `"briefing"` or `"status"` when nothing on the bus won. `expires_at` is null for the briefing. `rotation` is null when there is a single winner.
- The compositor re-evaluates every 5 s and rewrites the file only when the decision changes (so `decided_at` is the time of the last change).
- Clients poll every 5 s, navigate only when `url` changes, and show their own status card when the pointer has been unreadable for 30 s.

### Beacon (the focus input)

`focus/<host>-<session8>.json`, written by the session heartbeat on each beat (about every 30 s while a session is using tools):

```json
{
  "schema": 1,
  "host": "thinkpad",
  "session": "19ca7047",
  "repo": "lentago/brasenia",
  "cwd": "/home/cpitzi/repos/lentago/brasenia",
  "origin": "operator",
  "ts": "2026-10-07T12:00:00Z"
}
```

- `repo` is `owner/name` from the `origin` remote of the git repository containing `cwd`, or null when `cwd` is not inside a GitHub clone. A null `repo` produces no focus pane.
- A beacon is stale when `ts` is older than 10 min; the focus producer deletes stale beacons.
- Bullpen workers will write the same shape with `origin: "fleet"` (a later claytonia item).

### Focus pane

One pane per distinct `repo` with a fresh beacon, at `panes/focus-<owner>-<name>/`. `pane.html` follows the pane contract (1280 px wide, one 720 px band, dark background, 20 px minimum text, the bottom-right 220×50 px kept clear) and shows the repo's open pull requests (number, title, author, age, draft flag, check and review state), the latest completed `main` workflow conclusion, and, when `http://pub.lan/viewport/pipeline.json` exists, the change-pipeline row for that repo. Data comes from the unauthenticated GitHub REST API (every lentago repo is public), cached per repo for at least 60 s. On an API failure the previous `pane.html` is kept and stamped "data as of HH:MM". The manifest is `class: focus`, `ttl_minutes: 10`, `origin: operator` if any fresh beacon for the repo is `operator`, `author: focus-producer@pub`, `repo` set. When no fresh beacon remains for a repo, its pane directory is removed.

## Live-ingest source type

*Added 2026-08-16 (kalmia#102 + [ADR-0007](adr/0007-live-rtmp-ingest-generic-path.md)).*

A generic `live` RTMP path on mediamtx is the first event-driven source type:
publisher presence on `live` is a binary, machine-readable signal that
something worth watching is happening — the rubric decides by observing
publish state, no remote involved. Any LAN RTMP producer (DJI Fly, OBS,
Larix, a GoPro) publishes to `rtmp://pub.lan:1935/live` and appears on the
TV; when the publisher drops, mediamtx's fallback wiring returns the display
to `board` automatically. Adding a second producer touches nothing
DJI-specific in the product or the runtime.

In v0 (before the Phase 2 compositor), the `live`→`board` fallback chain in
mediamtx acts as the rubric surrogate for this one decision. The ADR-0002
retry handler doubles as the source switcher — when the publisher drops and
mediamtx returns an error on the `live` playlist, the Roku's retry loop
rejoins and mediamtx transparently serves `board`. When Phase 2 lands,
publisher presence (via the mediamtx HTTP API) becomes a rubric *input* — a
virtual pane of class `live` — and the compositor gates the live path rather
than being silently overruled by the transport-layer fallback chain.

**Latency disclaimer — spectator use only.** DJI Fly's encode adds ~2–3 s;
the measured Roku HLS join latency (7–17 s, ADR-0001) applies equally on the
`live` path. Glass-to-glass is approximately **10–20 s**. This is appropriate
for a household display showing what the drone is seeing. It is **never a
piloting aid** — do not use it as a substitute for the controller's real-time
video feed.

**Phone-side networking.** RC-N-series DJI controllers use the phone's own
Wi-Fi connection (the controller handles the RF link to the drone
independently). Streaming works as long as the pilot stands within home Wi-Fi
range. The `live` path is LAN-only by construction — mediamtx is not
reachable from the internet.

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
- **Phase 1.5 (2026-08-16):** RTMP `live` ingest path added (kalmia#102);
  `live`→`board` fallback wiring as v0 rubric surrogate; first event-driven
  source type (`live` class at priority 70). Roku repoint from `board` to
  `live` pending bench validation against a live DJI Fly publisher
  ([live-ingest-spec.md](live-ingest-spec.md)).
- **Phase 2 (in progress, 2026-10-07):** pane bus + manifest + compositor
  rubric, the compositor on pub (LXC 114) publishing the pointer;
  `web/viewport/` exists on the share, and compositor v1 (`compositor/`,
  [#27](https://github.com/lentago/brasenia/issues/27)) implements rubric v1
  and [Contracts v1](#contracts-v1). Briefing and Grafana become the first two
  pane classes, with `focus` panes from the session heartbeat alongside. The Cast client
  ([ADR-0006](adr/0006-cast-web-receiver-second-client.md)) is the
  compositor's cheapest proving ground — the rubric/decision loop validates
  against native HTML rendering before touching the video adapter.
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
