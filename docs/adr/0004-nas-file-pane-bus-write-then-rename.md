# ADR-0004: Pane bus is NAS files with write-then-rename, manifest, and a TTL backstop

**Status:** Accepted (2026-07-20; reconstructed 2026-08-13)

## Context

Phase 2 (not yet built) needs a way for multiple independent writers (local
Claudes: laptop, fleet workers, Career Claude, and others) to hand panes to
the compositor without a central service. `docs/concept.md` specifies the bus
as plain files under a NAS share every host already mounts
(`web/viewport/panes/<pane>/`, each holding `pane.html` + `manifest.json`),
explicitly reusing "the claude-jobs idiom" — write-then-rename
(`pane.html.partial` → `pane.html`), manifest written last.

The design explicitly rejects a broker or daemon on the NAS ("no broker, no
daemon on the NAS"), and gets free debugging because the same share is
already browsable over the LAN webserver alongside the existing `pub.lan`
publish leg. TTL in the manifest is the backstop for writers that die without
cleaning up their own pane dir — writers are expected to delete their own
directory when an activity resolves, but the compositor drops expired
manifests regardless.

## Decision

The pane bus is plain files on the existing shared NAS mount, using
write-then-rename for `pane.html` and a JSON manifest (class/priority/ttl/
created/author) written last, with TTL as the sole backstop for writers that
don't clean up after themselves. No message broker or push service sits
between writers and the compositor.

## Alternatives

- **Recorded at the time:** none explicitly weighed in concept.md beyond the
  chosen design — the file-bus approach is presented as a direct reuse of an
  existing idiom (claude-jobs), not a decision made among several drafted
  options.
- **Retrospective — not considered at the time:** MQTT, since Home Assistant
  on this network already speaks it. Lateral — it's a reasonable fit for a
  genuinely event-driven bus, but for this specific low-frequency,
  already-mounted-filesystem problem it adds a broker as new shared
  infrastructure with its own uptime and credential surface, in exchange for
  push semantics this bus doesn't need: panes update at human/activity
  timescales (minutes), not real time, so periodic file scanning costs
  nothing meaningful.
- **Retrospective — not considered at the time:** WebSocket push from
  writers straight to the compositor. Worse — it couples every writer to the
  compositor's uptime and reachability at write time (a writer can't drop a
  pane while the compositor is redeploying), whereas the file bus lets
  writers succeed independently of whether anything is currently reading.

## Consequences

- Any host that already mounts the share can act as a writer with zero new
  credentials or services — consistent with the credential-free runtime
  posture ([ADR-0005](0005-product-runtime-split-with-kalmia.md)).
- Debugging is "look at the files" — the same share is web-browsable, so a
  stuck or malformed pane is inspectable without special tooling.
- The design trades push latency for simplicity: the compositor must
  scan/poll the bus rather than being notified, and correctness against a
  crash mid-write relies on write-then-rename (not TTL) to avoid ever
  exposing a partial `pane.html` — TTL only cleans up an already-complete but
  abandoned pane dir.
