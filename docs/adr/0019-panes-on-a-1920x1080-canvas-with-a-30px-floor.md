# ADR-0019: Panes are laid out on a 1920×1080 canvas at 2×, with a 30 px text floor

**Status:** Accepted (2026-10-29; #112). Amends the pane contract in
[`concept.md`](../concept.md#the-pane-contract) and the 3× rendering of
[ADR-0009](0009-office-roku-4k-hevc-over-ffmpeg-hls.md). Runtime in
lentago/kalmia#216; producers in #113.

## Context

Every screen is now a 4K Roku: the office Streaming Stick Plus and the
basement's 75-inch TCL Roku TV. Both mirror the one stream. The play room's
720p TCL was tried on 2026-10-29. It cannot decode the 4K HEVC stream, and
it was left out rather than given an H.264 rendition (#110).

The pane contract still dates from the 720p play room. Panes are laid out at
1280×720 CSS pixels and rendered at 3× to 3840×2160. That gives 4K sharpness
but no room: a band holds what a 720p screen held. The contract's numbers
are all in those units: 720 px bands, ≥20 px text, 24 px margins, and a
220×50 px clock corner.

The family brief's desk editions (`detail.html`, #56/#57) are the only 4K-native
layouts. They are laid out at 1920×1080 and zoom themselves into the 1280×720
viewport, so they land at an effective 2×. Their text is 18–22 px at 1920,
which is 36–44 device pixels against the 60 of the contract's 20 px floor.
The renderer prefers `detail.html` whenever the pointer names a pane that
has one. There is one stream, so both screens show the desk edition, at the
desk and from the couch.

One unit also has three names. The contract calls a 16:9 screenful of a pane
a **band**, the renderer calls it a **page**, and a link pane's manifest
counts them as `source.screens`.

## Decision

- **The canvas is 1920×1080 CSS pixels per band, rendered at 2× to
  3840×2160.** 1920×1080 is the standard design size for a TV interface
  (Roku's own UI is built at it). It reaches 4K at an exact 2×, and it
  matches the remote's 1920×1080 peek images. A pane is 1920 px wide and
  1–4 bands tall (≤ 4320 px), and nothing straddles a 1080 px band boundary.
- **The text floor is 30 px.** That is today's floor at the same physical
  size: 20/720 of the screen height is 30/1080, about 2.8%, or about an inch
  on the 75-inch set. The other numbers scale the same way:
  - safe margins are 36 px;
  - the clock corner is 330×75 px.

  The stream's clock overlay keeps its size in device pixels, so it still
  fits that corner.
- **The floor binds every pane the shared stream shows, except link panes.**
  A link pane's page belongs to someone else, and the contract already
  cannot hold it to any of these rules. Every screen mirrors one stream, so
  one floor serves the desk and the couch alike. A
  denser layout for one screen would need its own stream, at about 1.4 cores
  per 4K encoder (ADR-0010). A pane directory may still hold other
  renditions for a client that pins one, but the stream stops preferring
  `detail.html` once the family brief's panes move to the new canvas.
- **Terms.**
  - A **pane** is the unit producers make: a directory holding `pane.html`
    and `manifest.json`.
  - A **band** is one 16:9 screenful of a pane.
  - A **rendition** is another HTML file in a pane's directory.

  Docs and new code say "band", not "page" or "slide". The manifest field
  `source.screens` keeps its name, because renaming a Contracts v1 field
  breaks every writer of it. It is documented as a count of bands. The
  renderer's own "page" wording and its `BRASENIA_PAGE_DWELL` setting are
  renamed in kalmia#216.
- **Migration is opt-in per pane.** A pane declares the new canvas in its own
  markup with `<meta name="brasenia-canvas" content="1920x1080">`, so the
  manifest, pointer and line-up are unchanged. The renderer lays a declaring
  pane out at 1920×1080 at 2×. A pane without the tag renders exactly as
  today: 1280×720 at 3×, under the old numbers. Producers declare the tag
  only after the renderer supports it (kalmia#216). Before that, a pane laid
  out for 1920 would be shot through the 1280×720 viewport. When the last producer and
  the compositor's status card have moved, the contract section in
  `concept.md` is rewritten for the new canvas. At that point 1280×720 panes
  are no longer supported.
- **Link panes are unchanged.** They keep their own `source.viewport`,
  default 1280×720. A web page sizes its text for a desktop browser, so
  laying it out wider would only make that text smaller. A slot that wants
  more room already sets `viewport`.

## Consequences

- **The office loses its denser desk editions.** The family brief's
  `family-today` and `family-week` get the 1920 canvas at the 30 px floor.
  They keep what the desk editions added where it fits, or spread it across
  bands. The 18–22 px desk editions then go off the stream. Detail that
  doesn't fit at the floor leaves the wall.
- **A band gains no lines of text at the floor.** At the same physical text
  size, a 1920×1080 band holds what a 1280×720 band holds. What changes is
  finer control: images, rules, charts and smaller non-text detail get 1.5×
  the CSS pixels, and layouts snap to the grid TV interfaces use.
- **Every producer that writes `pane.html` moves** (#113): family-brief,
  fleet, focus, grafana, home and pipeline, and the compositor's status card.
  Each one moves on its own and updates its tests that pin 1280/720. Nothing
  changes on the wall until a producer opts in. The links producer writes
  only link panes, which have no `pane.html` and keep their own viewport, so
  it does not move.
- **The runtime change is small** (kalmia#216). The renderer reads the meta
  tag and picks the canvas and scale. The stream stays 3840×2160 HEVC, and
  the encoder and its clock overlay do not change.
- **Every screen must be 4K.** A screen that cannot decode the stream is not
  a screen. Adding an HD Roku would mean reopening #110's H.264 rendition.

## Alternatives considered

- **Keep 1280×720 at 3×.** It needs no work, but the contract stays shaped
  by a 720p screen that is gone. It also leaves the desk editions as a
  side door that breaks the floor on every screen.
- **3840×2160 CSS at 1×.** Chromium already rasterizes text at device
  resolution at 2×, so this only doubles every number in the contract
  (60 px text, 72 px margins) and gains nothing.
- **A lower floor for the office.** One stream means one floor. The
  basement shows whatever the office shows, from across a room. A lower
  floor needs a per-screen stream (ADR-0010), a decision for another day.
- **A manifest field for the canvas.** The renderer works from the pointer
  and line-up, so a manifest field would have to be threaded through both
  (a Contracts v1 change). The meta tag lives in the self-contained HTML the
  renderer already loads.
