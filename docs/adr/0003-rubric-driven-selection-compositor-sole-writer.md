# ADR-0003: Rubric-driven pane selection; the compositor is the sole screen writer

**Status:** Accepted (2026-07-20; reconstructed 2026-08-13)

## Context

`docs/concept.md` frames the product identity itself around this: "one
always-on screen whose content is chosen by **a rubric, not a remote**" (also
the README tagline). Phase 0/1 (both done 2026-07-20 per the concept doc's
migration path) ran with manual pane switching — a human swapping loops
between the morning brief and Grafana. That doesn't scale as more Claudes and
activity sources want screen time.

The documented model is three nouns: **Pane** (self-contained HTML plus a
manifest declaring class/priority/TTL), **Rubric** (a deterministic,
versioned precedence policy — "not vibes"), **Compositor** (the only writer
to the screen; falls back to the briefing, then to a status card if even the
briefing is missing). Rubric v0 is already specified as a table —
`alert`(100) / `attention`(80) / `activity`(60) / `ambient`(40) /
`briefing`(0), each with a default TTL, ties breaking by recency. Governance
is explicit: Claudes only ever write or remove their own pane directories;
the compositor alone decides what actually shows.

Two items are recorded as still open in concept.md's "Open questions": (1)
whole-screen rotation vs. band-level composition when 2+ high-priority panes
are live, and (4) whether a Grafana pane stays a special `/render`-API type
or gets standardized through `pane.html` like everything else.

## Decision

Pane selection is governed by a single deterministic, versioned rubric
(priority class + TTL decay, checked into the repo like code), and the
compositor is the only component that writes to the screen — no writer,
including any Claude, ever pushes pixels directly.

## Alternatives

- **Recorded at the time:** continue manual pane switching (a human picks
  what's showing) — this is what Phase 0/1 already did, and is explicitly
  the thing the rubric+compositor model replaces because it doesn't scale
  past one operator manually swapping loops.
- **Retrospective — not considered at the time:** let each writer render
  directly to the shared frame/stream, coordinating by convention instead of
  through a gatekeeper. Worse — it reintroduces exactly the race "the
  compositor is the only writer" exists to prevent (two writers stomping the
  same frame), and removes the one place a reviewable policy can live.
- **Retrospective — not considered at the time:** a priority queue driven by
  a learned/heuristic "interestingness" ranking instead of a fixed rubric
  table. Worse for this use case — it trades a reviewable, deterministic,
  versioned policy for an opaque one, directly contradicting the stated
  design goal ("deterministic, versioned... not vibes") for a household
  display where predictability matters more than cleverness.

## Consequences

- Adding a pane class or changing precedence is a reviewable diff to the
  rubric table, not a runtime behavior change buried in code.
- The compositor becomes a single point of failure for what appears on the
  screen; concept.md already designs a fallback chain (rubric → briefing →
  status card) to keep that failure mode graceful.
- The two open questions (rotation vs. band composition; Grafana pane type)
  are unresolved design debt inherited by whoever builds Phase 2 — this ADR
  records the model, not the answers to those questions.
