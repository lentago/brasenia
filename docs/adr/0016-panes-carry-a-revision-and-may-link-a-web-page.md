# ADR-0016: Panes carry a content revision, and a pane may link a web page

**Status:** Accepted (2026-10-29; #96). **Amended by
[ADR-0020](0020-only-the-rubric-and-the-remote-change-the-wall.md)
(2026-10-29): a link pane shows one band** (`source.screens` is 1), **and
its `dwell` is accepted but ignored**, as for every pane. Amends Contracts v1 in
[`concept.md`](../concept.md#contracts-v1); additive, so existing writers and
clients keep working.

## Context

The viewport latency work ([#95](https://github.com/lentago/brasenia/issues/95),
[ADR-0015](0015-cap-the-roku-lag-by-rejoining.md)) found two gaps in the
contract.

**When to render again.** The Roku adapter on LXC 118 re-renders the shown
pane when the pointer's `decided_at` moves, or on a timer. The compositor
counted a moved `expires_at` as a new decision. Producers renew their panes
every minute by rewriting `created`, so most resting panes were re-rendered
every minute whether or not they had changed. A pane that kept its manifest
(`search-map`) waited for the timer, which was 10 minutes until kalmia#193.
File times cannot tell the two apart: producers rewrite `pane.html` every
minute even when nothing changed. Concept open question 2 had asked whether
manifests should declare their cadence.

**What fills a slot.** Every slot was a page our own producers wrote. The
household wants to put an existing web page on the wall: a Grafana dashboard,
or a pull request's page instead of a custom pane about it.

## Decision

- **A content revision, `rev`.** The compositor hashes each pane's
  `pane.html` (SHA-256, first 12 hex digits). It re-reads a page only when its
  file time or size changes. `rev` goes into `current.json` for the shown
  pane, and into each `lineup.json` item. The briefing carries its page's
  `rev` too.
- **A decision is what is shown, plus its revision.** A new `rev` moves
  `decided_at`. A renewal that only moves `expires_at` rewrites the pointer
  with the new expiry but keeps `decided_at`, so a client that re-renders on
  `decided_at` now re-renders exactly when content changes. The compositor's
  log line still marks only a change of pane, fallback or rotation.
- **Link panes.** A manifest may carry `source`:
  `{"url", "theme", "screens", "viewport", "refresh_s"}`, with defaults for
  all but `url`. Such a pane needs no `pane.html`, and everything else (class,
  TTL, origin, dwell, the rubric, the line-up, the peek, Left/Right) is
  unchanged. The pointer's `url` is the page, and its `source` field carries
  the display settings. A link pane's `rev` is the hash of its validated
  `source`, so changing the page or how it is shown is new content; a client
  re-renders it every `refresh_s` as well.
- **Link panes are off until the renderer is ready.** The compositor admits
  them only with `--link-panes`. Without it, a link pane is listed on the
  board as `off`, logged once, and kept out of the pointer and the line-up.
  LXC 118's renderer runs Chromium without its sandbox, on the grounds that it
  renders only our own pub.lan pages. Pointing it at outside sites waits for
  [kalmia#194](https://github.com/lentago/kalmia/issues/194), which adds an
  allowed-sites list and the sandbox, and turns the flag on in the same
  change.
- **Pages that need a login are not link panes.** pub renders those into
  ordinary panes and keeps the credential
  ([#98](https://github.com/lentago/brasenia/issues/98)), so the renderer
  stays credential-free.

## Consequences

- **Old writers and readers are unaffected.** A manifest without `source`
  validates exactly as before. The pointer and the line-up gain fields, and
  existing clients ignore fields they do not know.
- **Fewer wasted renders.** A pane whose content did not change (`fleet`, for
  instance) is no longer re-rendered every minute. One whose page changes
  every minute (Home and Weather stamp the time) still is, which is the point.
- **The pointer changes once on upgrade.** A pointer saved before this change
  lacks the new fields, so the first decision after deploying counts as new.
- **`pane claim --url` and standing slots are #97**, which builds on this.

## Alternatives considered

- **File times as the revision.** Rejected: producers rewrite their pages
  every minute whether or not anything changed.
- **Each manifest declares a render cadence.** Rejected for file panes: a
  hash re-renders exactly when content changes, and a producer cannot get it
  wrong. Link panes declare `refresh_s` because they have no file to hash.
- **Link panes as a `pane.html` that redirects to the page.** No contract
  change, but it carries no display settings and no revision, and the board
  could not tell a link from a page.
- **Turn link panes on now.** Rejected: an outside page in an unsandboxed
  browser on the LAN.
