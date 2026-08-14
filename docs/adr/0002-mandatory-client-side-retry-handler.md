# ADR-0002: The retry handler is the product

**Status:** Accepted (2026-07-20; reconstructed 2026-08-13)

## Context

The 2026-07-20 validation session ran two versions of the Roku app back to
back. v1 was a bare `Video` node; when ffmpeg (the publisher) was killed and
restarted, mediamtx destroyed and recreated the HLS muxer, and the bare
`Video` node landed in `state=error` and never recovered — measured **0
reconnects in 90 s**, still frozen at 19:16:35 after a 19:15:17 kill
(`docs/validation-notes-2026-07-20.md`).

v2 added a state observer (on `error`/`finished`: stop, wait via a 3 s Timer,
re-set content, play). Re-tested: kill at 19:18:12, restart at 19:18:22, Roku
rejoined at 19:18:23 — about 1 second after the stream returned — fully
unattended.

The wall display runs unattended by design; any renderer restart, deploy, or
container reboot on the runtime side (owned by kalmia) kills and restarts the
HLS publisher the same way the test did. `CLAUDE.md` in this repo now flags
the retry handler as **"Never remove"**, restating the `state=error` failure
mode explicitly, alongside the requirement that the stream URL keep the
`?cookieCheck=1` suffix — mediamtx ≥1.19 302-redirects without it, and
Roku's HLS client doesn't reliably follow the redirect's session dance.

## Decision

The client-side retry handler (state observer + 3 s Timer, re-set
content/play loop) in `roku-app/components/VideoScene.xml` is a mandatory,
never-remove piece of the product — not an optional resilience nicety. It
ships baked in, together with the pre-baked `?cookieCheck=1` URL suffix.

## Alternatives

- **Recorded at the time:** a bare `Video` node with no retry logic (v1) —
  this was the shape actually tried first; it failed the validation's own
  recovery criterion outright and was not a viable option once that was
  observed.
- **Retrospective — not considered at the time:** fix recovery server-side —
  configure mediamtx to keep the HLS session alive across a publisher
  restart instead of tearing it down. Lateral-to-worse — it doesn't remove
  the need for client resilience (a TV reboot, app crash, or network blip
  still needs the Roku to rejoin on its own), and the muxer-teardown behavior
  here is a mediamtx implementation detail, not something this repo
  controls.
- **Retrospective — not considered at the time:** a runtime-side supervisor
  that detects a stuck Roku session and force-restarts the app remotely
  (e.g. via Roku's ECP). Worse — Roku's ECP can launch/deep-link channels,
  but the display has no feedback channel for the runtime to *detect* stuck
  playback from outside; this would need new runtime infrastructure and
  credentials on a container that is deliberately credential-free (see
  [ADR-0005](0005-product-runtime-split-with-kalmia.md)), to solve a problem
  a few dozen lines of BrightScript already solve for free.

## Consequences

- Every future Roku app change must preserve the observer + Timer retry and
  the `?cookieCheck=1` URL; `CLAUDE.md` enforces that explicitly rather than
  relying on it being "obviously" needed.
- The display tolerates publisher restarts, container reboots, and mediamtx
  redeploys without anyone touching the TV — which is what makes the
  credential-free, laptop-free runtime split (ADR-0005) viable in practice,
  not just on paper.
- The retry logic is validated only against a clean publisher kill/restart;
  other failure modes (a hung-but-not-erroring stream, a Roku network blip
  that never trips `state=error`) remain unvalidated risk.
