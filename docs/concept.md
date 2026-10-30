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

*Amended 2026-10-28: the office Roku plays 4K HEVC and is the viewport's
screen; Roku is the client platform and the Cast client is retired
([ADR-0009](adr/0009-office-roku-4k-hevc-over-ffmpeg-hls.md),
[ADR-0010](adr/0010-roku-is-the-client-platform.md)).*

*Amended 2026-10-29: the pointer and the line-up carry each pane's content
revision, and a pane may be a link to a web page
([ADR-0016](adr/0016-panes-carry-a-revision-and-may-link-a-web-page.md),
[#96](https://github.com/lentago/brasenia/issues/96)).*

Brasenia (watershield) carpets New England ponds with small floating leaves —
little panes resting on the water's surface. **brasenia** is the shared window
into what the Claudes working our estate (everything we run, on-prem and in the
cloud) are doing: one always-on screen whose
content is chosen by a rubric, not a remote. The Family Brief is the resting
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
      │           ├── pane.html      (one 1920×1080 band, ADR-0019/0020)
      │           └── manifest.json  (class, ttl, created, author, origin)
      ▼
 pub (LXC 114, mounts and serves the share) — compositor:
      1. scan manifests → drop expired → rank via rubric
      2. publish the decision — viewport/current.json, the pointer
         every client follows (http://pub.lan/viewport/current.json)
      ▼
 client adapters — one per screen; adding one must not touch the others
      │
      ├─ Roku/HLS adapter (the office — ADR-0009; the viewport's screen)
      │    3. render the pointer's pane, one band (headless chromium,
      │       throwaway profile) → 3840×2160 → frame.png
      │    4. ffmpeg (image2pipe → HEVC 5 fps + AAC) → HLS on tmpfs → :8080
      │    ▼
      │  Roku dev channel (roku-app/ in this repo — auto-retry Video node;
      │  remote Up/Down peeks through lineup.json images, ADR-0012;
      │  Left/Right sets the default resting pane, ADR-0013)
      │       → office Roku Streaming Stick Plus, 4K display
      │
      └─ (Cast adapter — ADR-0006 — retired 2026-10-28; Roku is the client
          platform, ADR-0010)
```

The bus is plain files on the share every host already mounts — no broker, no
daemon on the NAS, browsable at `http://pub.lan/viewport/` for free debugging.
The compositor also writes the rubric board, `http://pub.lan/viewport/rubric.html`:
the decision, the class ladder with each live pane on its rung, the fallback
chain (flagging a stale brief), and why each pane is or isn't showing.
Pub stays the *publisher* (Drive → web, credentials live only there); brasenia
is the *renderer* and needs no credentials at all.

The compositor's real output is the **decision**, not pixels — the
shoot→slice→encode→HLS chain is the *Roku client's adapter*, not the product.
A Chromecast web receiver was a second client
([ADR-0006](adr/0006-cast-web-receiver-second-client.md)) until it was retired
on 2026-10-28. Roku is now the client platform
([ADR-0010](adr/0010-roku-is-the-client-platform.md)): every screen is a Roku
running this repo's dev channel, and Home Assistant, which speaks Roku's
ECP, is where Roku-side automation such as powering a screen or relaunching
the channel will go.

**The office Roku (2026-10-28).** The play-room Roku was factory reset and
retired. The Roku/HLS adapter now serves a 4K Roku in the office instead,
streaming HEVC at 3840×2160 from ffmpeg-written HLS
([ADR-0009](adr/0009-office-roku-4k-hevc-over-ffmpeg-hls.md)). With the
Chromecast offline the same day, that Roku is the viewport's only screen. It
follows the pointer (#59). It is LAN-self-contained.

### Degraded mode: internet outage

The display is LAN-self-contained. The Roku plays an HLS stream from LXC 118,
which reads only `http://pub.lan/`, so an internet outage leaves the screen up.
It shows what pub already has; the Family Brief simply stops updating until
pub can reach Drive again. The Cast-era regression accepted on 2026-10-13
([#12](https://github.com/lentago/brasenia/issues/12)), a dark display
whenever the receiver needed relaunching without internet, ended with the Cast
client ([ADR-0010](adr/0010-roku-is-the-client-platform.md)).

**Compositor placement (2026-10-07).** The compositor runs on pub (LXC
114), from the `/srv/brasenia` checkout kalmia already keeps there, because
pub mounts and serves the share and LXC 118 has no NAS mount by design. LXC
118 stays a client adapter: it reads the pointer over HTTP like any other
client. The runtime half (unit, schedule, checkout) is kalmia's
([kalmia#140](https://github.com/lentago/kalmia/issues/140)).

## The pane contract

> **One band, nothing rotates ([ADR-0020](adr/0020-only-the-rubric-and-the-remote-change-the-wall.md)).**
> A pane is one band. Where this section or Contracts v1 says 1–4 bands or
> `source.screens` up to 4, ADR-0020 supersedes it, pending the rewrite in #118.

> **Moving to a 1920×1080 canvas ([ADR-0019](adr/0019-panes-on-a-1920x1080-canvas-with-a-30px-floor.md)).**
> A pane that declares `<meta name="brasenia-canvas" content="1920x1080">` is
> laid out 1920 px wide in 1080 px bands and rendered at 2×. It uses ≥30 px
> text, 36 px safe margins and a 330×75 px clock corner. The 30 px floor binds
> every pane the shared stream shows except link panes. Producers move one at a
> time (#113), and declare the tag only after the renderer supports it
> (lentago/kalmia#216). Until then the 1280×720 rules below apply. A **band**
> is one 16:9 screenful of a pane.

- `pane.html`: self-contained (inline CSS, no external assets/JS), body width
  1280px, height an exact multiple of 720px (≤ 2880). Every 720px band must
  stand alone — nothing straddles a boundary. Dark background, ≥20px body
  text, 24px safe margins, bottom-right ~220×50px of each band kept clear
  (clock overlay is composited there).
- A link pane (a manifest `source`, ADR-0016) has no `pane.html`. Its page is
  someone else's and cannot be held to this contract. The client lays it out
  at `source.viewport`, shows `source.screens` bands of it, and asks for
  `source.theme`; the clock still covers the bottom-right corner.
- Sizes are CSS pixels. A client may render a pane at an integer scale (the
  office Roku renders at 3×, 3840×2160 device pixels), and the clock and its
  clear corner scale with it, so design for 1280×720 CSS pixels only.
- A pane directory may also hold other renditions beside `pane.html`. The
  compositor reads only `pane.html` and `manifest.json`, and a client reaches
  a rendition only by pinning to its URL. The shared stream shows
  `pane.html` and never prefers a rendition, because everything it shows is
  held to the 30 px floor (ADR-0019, lentago/kalmia#217). Until #217 is
  deployed on LXC 118, the renderer still prefers a `detail.html` if one
  exists, and none does: the family brief's desk editions were retired for
  being below the floor (#115). A rendition goes when its pane does.
- `manifest.json`: the fields and liveness rule are in
  [Contracts v1](#manifestjson).
- Writers use write-then-rename (`pane.html.partial` → `pane.html`), create
  the manifest last, and delete their own pane dir when the activity resolves.
  TTL is the backstop for writers that die without cleaning up.

## Rubric v1

> **No ties, no rotation ([ADR-0020](adr/0020-only-the-rubric-and-the-remote-change-the-wall.md)).**
> The rubric ranks live panes in a strict order, and the first one shows.
> Where this section describes panes taking turns by `dwell_s`, ADR-0020
> supersedes it, pending the rewrite in #121.

*Replaces rubric v0 (2026-10-07): adds `focus` at 50, the `origin`
tie-break, and rotation by `dwell_s`.*

The priorities below, the default dwell and the briefing fallback's maximum
age are defaults. The household can override them from
`http://pub.lan/viewport/configure.html`, beside the rubric board. Each change
is a pub-signals line in `signals/rubric.jsonl` that the compositor validates
and applies within seconds, and the effective values are in
`viewport/rubric.json`
([ADR-0011](adr/0011-rubric-settings-on-the-share.md)).

**The default resting pane** (`default.pane`, #83). Several `ambient` panes
(the Family Brief's today and week, Home, Weather and Fleet, #86) share the
resting rung and take turns in a fixed order (by id), each for its
`dwell_s`. The household can name one as the
default, from the configurator's dropdown or with Left/Right on the Roku
remote: when it is live it ranks first in its rung and holds, and the others
wait. It only orders the resting panes, so `focus`, `activity`,
`attention` and `alert` panes still take over when they appear, and the
default returns after them.

**Standing slots** (`link.<pane-id>`, #97,
[ADR-0018](adr/0018-standing-slots-are-household-settings.md)). The household
can keep any web page on the wall as a resting pane, from the configurator's
Standing slots section.
- **The setting:** each slot is one setting whose value is a JSON object, the
  slot's `title` plus a link pane's `source` fields. `set` adds or changes it
  and `undo` removes it. The compositor validates it like a manifest `source`.
- **The producer:** `producers/links` reads the validated slots from
  `viewport/rubric.json` and keeps one `ambient` link pane per slot (author
  `links-producer@pub`), renewed every 30 s, and takes it down when the slot
  goes.
- **On screen:** slots rest and rotate like the other resting panes; Left/Right
  steps through them and can make one the default. They show only once link
  panes are on.

| Priority | Class | Default TTL |
|---|---|---|
| 100 | `alert` | 60 min |
| 80 | `attention` | 240 min |
| 60 | `activity` | 60 min |
| 50 | `focus` | 10 min |
| 40 | `ambient` | while fresh |
| 0 | `briefing` | never |

Ranking: priority descending, then `origin` (`operator` before `fleet`), then `created` descending, except among `ambient` panes, which keep a fixed order by id because each producer rewrites `created` on its own cadence (#86). Panes tied on priority and origin rotate; each shows for its `dwell_s` (default 20 s) before the next. Only the top group rotates; lower groups wait. Fallback ladder: no live pane → the briefing slot (below), skipped when it is absent or older than the household's `briefing.max_age_hours` → `status.html`, which the compositor writes with the reason.

**The briefing slot** (`viewport/briefing/`, #76) holds what the fallback shows: `pane.html` (the pane contract) and `manifest.json` (`schema` 1, `title`, `published`: when the brief itself was generated, RFC 3339, and `author`). The family-brief producer keeps it filled with the latest Family Brief whatever its age. The `family-today` pane leaves the bus once the brief is older than yesterday; the slot stays, saying how old it is. The compositor names `pane.html` in the pointer, titled from the manifest, and judges the age by `published` rather than the file time, because the producer rewrites the page every minute. Writers follow the bus rules: write-then-rename, and leave a slot another author owns alone. It replaced `http://pub.lan/brief/`, the morning brief, which stopped publishing on 2026-08-31.

## Contracts v1

These are the contracts every Phase 2 piece builds to (the compositor, the
clients following the pointer, the focus producer, and the session
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
- `lineup.json`, what a client may step through without changing that decision (below).
- `briefing/`, the briefing slot the fallback shows (see Rubric v1).
- `rubric.html`, `configure.html` and `rubric.json`, the rubric board, its configurator and the effective settings (ADR-0011).
- `status.html`, the status card the compositor writes as the fallback of last resort.
- `state/`, compositor rotation state.

Writers use write-then-rename for every file (`x.partial` → `x`) and write `manifest.json` last. A writer relinquishes by deleting its own pane directory. The compositor is the only writer of `current.json`, `lineup.json`, `status.html`, the board files and `state/`.

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

- `class` is one of `alert`, `attention`, `activity`, `focus`, `ambient`, `briefing`. `title`, `created` (RFC 3339, UTC), `ttl_minutes`, `author` are required.
- `origin` is `operator` or `fleet` (default `fleet`); it is the tie-break within a class.
- `repo` (`owner/name`), `dwell_s` and `done_when` are optional. v1 ignores `done_when`.
- `source` is optional and makes the pane a **link pane** ([ADR-0016](adr/0016-panes-carry-a-revision-and-may-link-a-web-page.md)): the screen shows a web page instead of `pane.html`. It is `{"url": "https://…", "theme": "dark", "screens": 1, "viewport": [1280, 720], "refresh_s": 60}`.
  - `url` (http or https) is required; the other fields have the defaults shown. The pointer is readable on the LAN, so a `url` with a user or password, or with a query or fragment parameter that usually carries a secret (`token`, `signature`, `key`, …), is malformed. That check is a heuristic: a link pane's URL must be token-free.
  - `theme` is `dark` or `light`; `screens` is 1–4 bands of the page to show; `viewport` is the CSS size to lay the page out at (240–3840 each); `refresh_s` (at least 10) is how often to render it again.
  - Other keys are ignored. The compositor shows link panes only with `--link-panes`, which stays off until the renderer has its allowed-sites list and Chromium's sandbox ([kalmia#194](https://github.com/lentago/kalmia/issues/194)).
- A pane is live when both files exist (a link pane needs only `manifest.json`), neither is a `.partial`, the manifest parses, and `created + ttl_minutes` is in the future.

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
  "rotation": {"index": 0, "of": 2, "dwell_s": 20},
  "rev": "8dddf601435e",
  "source": null
}
```

- `pane` is null and `fallback` is `"briefing"` or `"status"` when nothing on the bus won. `expires_at` is null for the briefing. `rotation` is null when there is a single winner.
- `rev` is the shown page's revision: the first 12 hex digits of the SHA-256 of its `pane.html`, or of a link pane's validated `source`. It is null for the status card.
- `source` is the link pane's validated `source`, defaults filled in, and `url` is then its page; `source` is null for every other pane.
- The compositor re-evaluates every second (pub runs `--interval 1`, kalmia#193). It rewrites the file when the pointer changes. A new pane, fallback, rotation step or `rev` is a new decision and moves `decided_at`. A renewal that only moves `expires_at` rewrites the file but keeps `decided_at` ([ADR-0016](adr/0016-panes-carry-a-revision-and-may-link-a-web-page.md)).
- Clients poll every few seconds (the Roku adapter every second), render again when `decided_at` changes, and show their own status card when the pointer has been unreadable for 30 s.

### lineup.json (what a client may step through)

`{"schema": 1, "decided_at", "items": [...]}`, rewritten when it changes. `items` are the live panes in rubric order, then the briefing slot (id `_briefing`, not a valid pane id) when it exists and no live pane is the one its manifest names in `pane`. Each item has `id`, `title`, `class`, `priority`, `url` (the pane's `pane.html`, or a link pane's page), `showing` (true for the one the pointer names), `default` (true for the household's default resting pane), `rev` and `source` (as in the pointer). It exists for the Roku remote: Up/Down peeks at an item without changing anything (#80), and Left/Right sets `default.pane` among the `ambient` items, through the same logged settings channel as the configurator (#83).

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

One pane per distinct `repo` with a fresh beacon and something to show, at `panes/focus-<owner>-<name>/`. A repo with no open pull requests, a fine latest `main` run (or none) and no pipeline row is quiet and gets no pane, so an empty table never outranks the resting surface; the pane returns when any of that changes. `pane.html` follows the pane contract (1280 px wide, one 720 px band, dark background, 20 px minimum text, the bottom-right 220×50 px kept clear) and shows the repo's open pull requests (number, title, author, age, draft flag, check and review state), the latest completed `main` workflow conclusion, and, when `http://pub.lan/viewport/pipeline.json` exists, the change-pipeline row for that repo. Data comes from the unauthenticated GitHub REST API (every lentago repo is public), cached per repo for at least 60 s. On an API failure the previous `pane.html` is kept and stamped "data as of HH:MM" (household time, `--tz`, default `America/New_York`). The manifest is `class: focus`, `ttl_minutes: 10`, `origin: operator` if any fresh beacon for the repo is `operator`, `author: focus-producer@pub`, `repo` set. When no fresh beacon remains for a repo, its pane directory is removed.

## Live-ingest source type

*Added 2026-08-16 (kalmia#102); retired 2026-10-29
([kalmia#213](https://github.com/lentago/kalmia/issues/213)).*

RTMP live ingest put a feed on the wall, such as a drone flight, through
mediamtx's `live` path on LXC 118. The rubric kept a `live` class at priority
70 for it. Roku is the focus, so the ingest is retired. mediamtx is gone from
the runtime ([kalmia#224](https://github.com/lentago/kalmia/pull/224)), and the
class went with it (#122): a manifest with `class: live` is now skipped as an
unknown class, and `pane claim --class live` is a usage error. The design, its
latency and its networking notes stay in
[ADR-0007](adr/0007-live-rtmp-ingest-generic-path.md). Bringing it back needs a
new decision that supersedes it.

## Governance

A standardized snippet ships in the global `~/.claude/CLAUDE.md` (and the
fleet worker prompts via claytonia): *what* deserves a pane (screen-worthy =
Chris would want to glance up and see it), the pane contract above, and the
rule that Claudes only ever write/remove their **own** pane dirs — the
compositor alone decides what shows. Same shape as the existing pub.lan
drop-folder and bullpen-dispatch instructions: capability documented once,
usable by every session. The canonical text is
[`claiming-the-display.md`](claiming-the-display.md).

## Migration path

- **Phase 0 (done 2026-07-20):** laptop streams brief/Grafana to the TV;
  manual pane switching; publisher on pub.
- **Phase 1 (done 2026-07-20, same night):** streaming stack moved to the
  dedicated viewport LXC (118, pve4, hostname `lunaria`, renamed `brasenia` and
  rebuilt 2026-10-29 by kalmia#63) via kalmia (TF + ansible role); Roku
  app repointed; laptop retired from the loop.
- **Phase 1.5 (2026-08-16):** RTMP `live` ingest path added (kalmia#102);
  `live`→`board` fallback wiring as v0 rubric surrogate; first event-driven
  source type (`live` class at priority 70). Roku repoint from `board` to
  `live` pending bench validation against a live DJI Fly publisher
  ([live-ingest-spec.md](live-ingest-spec.md)). Retired 2026-10-29: RTMP
  ingest left the runtime (kalmia#224), and the `live` class left Rubric v1
  (#122).
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
- (2026-10-28) Roku plays H.264 only up to 1080p, so 4K needs HEVC; and
  Roku rejects an HLS playlist declaring `#EXT-X-VERSION:10`, which is what
  mediamtx's fMP4 variant writes
  ([ADR-0009](adr/0009-office-roku-4k-hevc-over-ffmpeg-hls.md)).
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
2. ~~Pane render cadence: compositor re-shoots the winner every N minutes —
   is 5 min fresh enough for `activity` panes, or should manifests declare it?~~
   **Answered (2026-10-29, ADR-0016):** a pane is rendered again when its
   `rev` changes, and a link pane, which has no file to hash, declares
   `refresh_s`.
3. Should the TV audio channel ever carry anything (TTS alert chime on
   `alert` panes)? The stream already has an AAC track of silence.
4. Grafana pane: keep the `/render` API approach (no browser needed) as a
   special pane type, or standardize everything through pane.html?
5. ~~Does brasenia eventually own the Roku app?~~ **Answered: yes** — this
   repo ships the BrightScript (`roku-app/`); CI-zipping it is a future nicety.
