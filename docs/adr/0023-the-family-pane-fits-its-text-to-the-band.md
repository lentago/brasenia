# ADR-0023: The family pane fits its text to the band, down to 20 px, and cuts nothing

**Status:** Accepted (2026-11-05, Chris). Amends
[ADR-0019](0019-panes-on-a-1920x1080-canvas-with-a-30px-floor.md) for the
`family-today` pane only.

## Context

`family-today` laid each day out in fixed slots: six rows of 93 px, two
lines each, at a fixed 33 px. Text that did not fit was cut with an
ellipsis: the time column (225 px) cut "10:00 - 11:00 AM" to "10:00 - 11…",
an item's description stopped after two lines, and the coverage callout
stopped after two lines with its third line bleeding out under the box. On
a quiet day the same slots left most of each column empty. A family brief
whose words are cut off can't be read from across the room, however big the
type is.

## Decision

- **Nothing on the pane is cut with an ellipsis.** Times, descriptions,
  the coverage callout, the decision strip and the edition wrap.
- **The pane picks one body size per render, from 46 px down to 20 px,**
  for both columns and the strip: the largest whose layout fits the band.
  A quiet day fills the space with big type; a busy one comes down.
- **The floor for this pane is 20 px, below ADR-0019's 30 px,** by Chris's
  call: smaller type beats cut-off type. The ladder only goes under 30 px
  when a day needs it to fit.
- **Only below the floor does a column end in "+N more on the board".**
- Rows are laid out side by side (time, then the description) or stacked
  (the time on its own line), whichever fits the larger size. A time never
  wraps in a side-by-side row.
- The pane has no scripts, so the producer estimates the layout from DejaVu
  Sans' advance widths (`family_brief_producer/metrics.py`), rounded up 3%,
  with a few pixels to spare, so it errs toward one line too many.

## Consequences

- Every other pane still holds to the 30 px floor. `family-week` still
  clamps its day bodies to two lines; it can follow this pane if wanted.
- The estimate ignores kerning and breaks only at spaces, so a column can
  end a line or so short of full; it does not overflow. If the pane's font
  ever changes, `metrics.py` must be regenerated.
