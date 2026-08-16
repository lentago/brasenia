# ADR-0007: Generic RTMP ingest path; fallback-chain switching; `live` as rubric source type

**Status:** Accepted (2026-08-16); fallback-switching validation pending (see
[live-ingest-spec.md](../live-ingest-spec.md))

## Context

kalmia#102 adds RTMP ingest to the viewport LXC's mediamtx instance: a
generic `live` path that any LAN RTMP producer can publish to, with mediamtx's
fallback wiring dropping the Roku to the `board` path when no publisher is
active. The first producer is DJI Fly's custom-RTMP live streaming (drone
flights on the wall TV); subsequent producers (OBS, Larix, GoPro, a second DJI
controller) must touch nothing DJI-specific in the product or the runtime.

This is a two-repo change. kalmia#102 is the runtime half (RTMP on, `live`
path, publish auth, fallback wiring); this ADR is the product-side record.

The layering principle the concept doc and ADR-0003 establish is: sources
*offer*, the rubric *selects*, adapters *carry*. That hierarchy must hold
regardless of whether the transport is HTML-pane-bus, HLS video, or RTMP
video:

- A source signals its presence and class.
- The rubric decides which claim is active (one place, versioned, deterministic
  — "not vibes").
- Adapters carry the decision to a screen (HLS chain for Roku; Cast receiver
  for Chromecast — ADR-0006).

In v0, no compositor exists, so the rubric cannot directly observe RTMP
publisher state. The decisions below record how the feature ships correctly
now and wires cleanly into Phase 2.

## Decisions

### 1. Generic `live` path, not a producer-specific one

The ingest path is named `live` and carries no producer-specific
configuration. Any LAN RTMP producer can publish to
`rtmp://pub.lan:1935/live` (with the publish token) and appear on the TV
without touching the runtime or the product. DJI Fly is the first producer,
not the defining one — the path's name reflects what it carries, not who
sends it.

### 2. Fallback-chain switching, not a compositor change

In v0, the `live`→`board` fallback wiring in mediamtx handles source
selection. When a publisher is active on `live`, mediamtx serves `live` HLS
to readers; when the publisher drops, mediamtx falls back to `board`. The
ADR-0002 mandatory retry handler, already on the Roku, doubles as the source
switcher: when mediamtx returns an error on the `live` playlist (publisher
gone), the Roku enters error state, the retry loop fires within ~3 s, and
the rejoin gets `board` transparently.

The fallback chain is **subordinate wiring, not a parallel authority**. It
hard-codes the one rubric rule that is correct for v0: *a live publisher
outranks the board*. It also functions as the degraded-mode failure floor —
when nothing else is running, the display returns to the briefing without
compositor involvement.

The alternative — delaying until the Phase 2 compositor handles this
switching actively — would block the feature on Phase 2 landing, add a new
failure mode (compositor crash = no video), and replicate what the HLS
fallback provides for free. The fallback chain is the right tool for the v0
single-source case; it is not the right tool once multiple source classes
compete, which is exactly the problem Phase 2 solves.

### 3. Publish auth on the `live` path; ADR-0005 compatibility

The `live` path carries a publish token (shared secret between DJI Fly's
custom-RTMP URL and mediamtx's path config in kalmia). This does not violate
ADR-0005's credential-free-container design for two reasons:

- **Narrow scope.** The token grants exactly one capability: the ability to
  push video onto the `live` path. It does not grant access to the LXC, the
  NAS, any agent, or any other service. A stolen token lets an attacker put
  video on the household TV; nothing else.
- **Correct owner.** The token lives in kalmia (the RTMP path auth config,
  managed secret); this repo holds no credentials. The product/runtime split
  is preserved — a compromise of the display leg still cannot reach anything
  credentialed.

Read access to `live` and `board` is unauthenticated, matching the existing
`board` behavior. No Roku-side credential is needed.

### 4. Recording explicitly out of scope

mediamtx does not record the `live` path to disk. The drone's SD card holds
higher-quality originals than any re-encoded RTMP stream. Recording to the
LXC would require explicit disk sizing, retention policy, and rotation — a
separate decision not made here.

## Layering and Phase 2 gating hook

The fallback chain is correct v0 wiring, not a permanent architecture. When
the Phase 2 compositor lands (ADR-0003, concept.md Phase 2):

- Publisher presence on the `live` path (detectable via the mediamtx HTTP API
  `/v3/paths/list`) becomes a rubric *input* — a virtual pane of class `live`
  at priority 70 (concept.md Rubric v0, updated 2026-08-16).
- The compositor evaluates it against other live panes via the rubric and
  publishes the selection as the current-pane pointer (ADR-0006).
- The compositor must be able to **gate** the live path — rank it below a
  higher-priority pane, suppress it, or preempt it at publisher-appearance —
  rather than being silently overruled by the transport-layer fallback chain.
  A Phase 2 `alert`-class pane must be able to outrank a live drone feed.

After Phase 2 lands, the `live`→`board` fallback chain should be removed or
demoted to pure failsafe (no publisher active *and* no compositor running), so
that the compositor is actually the sole policy authority per ADR-0003. The
fallback wiring acting as a rubric surrogate is a v0 debt item.

## Alternatives

### All-RTMP prioritized-reservation scheme

A general rubric mechanism was considered where publishers claim explicit RTMP
path priorities at publish time and mediamtx routes to the highest-priority
live publisher.

Rejected:

- It relocates the importance claim into the publishers — a remote with extra
  steps, directly contradicting ADR-0003's "rubric, not a remote" rule. The
  source should not decide its own rank; the rubric should.
- It can only express static ordinal precedence: no TTL, no decay, no
  rotation, no band composition. The rubric table can express all of these;
  the reservation scheme cannot.
- It cannot preempt at publisher-appearance. HLS fallback resolves only at
  reader-join (the Roku fetches a new manifest segment, not at the instant the
  publisher starts). The compositor, by contrast, can observe the mediamtx API
  continuously and push a new decision pointer immediately — a real preemption,
  not a segment-boundary approximation.

### DJI-specific ingest path (e.g. `dji-fly`)

Rejected — a named per-producer path makes adding a second producer a runtime
config change and implicitly encodes the producer's identity in the
infrastructure, which the fleet agnosticism principle prohibits. The source's
identity is the video it produces, not the path name.

### Compositor-driven switching now (pre-Phase 2)

Rejected — it blocks the feature on Phase 2 landing and introduces a new
failure mode (compositor crash = TV goes dark) for no net gain over the HLS
fallback already available.

## Consequences

- Adding a second LAN RTMP producer requires no product or runtime config
  change beyond publishing to the `live` path with the publish token.
- The v0 fallback chain short-circuits the rubric for the live-vs-board
  decision; this is intentional and temporary. Phase 2 must revisit this
  wiring — see the gating hook above.
- `live` is the first event-driven pane class in the rubric: publisher
  presence is a binary machine-readable signal with no TTL needed (the source
  disappears when the publisher drops, not on a timer).
- If bench validation finds that fallback switching does not work reliably
  under the `?cookieCheck=1` redirect (a known Roku/mediamtx concern from
  ADR-0001) on path-to-path transitions, v0 falls back to a manual Roku URL
  repoint via the existing `lunaria_tv_url` recipe, and this ADR records that
  outcome after the validation run.
- The `live` path's latency (DJI encode ~2–3 s + measured 7–17 s HLS join =
  ~10–20 s glass-to-glass) makes this a spectator display only — never a
  piloting aid. This is documented in concept.md and the acceptance spec; it
  is a product constraint, not a defect to optimize away.
- Per ADR-0005: the publish token lives in kalmia; this repo holds no
  credentials. The mediamtx path config (RTMP on, `live` path, auth, fallback
  to `board`) is runtime and belongs in kalmia.
