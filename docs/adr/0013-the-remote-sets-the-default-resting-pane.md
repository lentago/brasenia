# ADR-0013: The remote sets the household's default resting pane

**Status:** Accepted (2026-10-28; #83). Amends
[ADR-0012](0012-the-remote-peeks-it-never-decides.md): Up/Down still only
peeks, and Left/Right now changes one rubric setting. The `live` class it
lists among the interrupting classes was retired on 2026-10-29 (#122), along
with RTMP live ingest.

## Context

ADR-0012 kept the Roku remote out of the decision: Up/Down peeks, and nothing
it does changes what the compositor shows. The ladder then gained a second
resting pane, the Family Brief's "This week" (`family-week`) beside
`family-today`. Two `ambient` panes tie on priority, so they take turns, and
Chris wanted Left/Right on the main view to cycle them and set the new
default.

He chose **resting panes only**. The remote may pick which `ambient` pane is
the resting surface, but it may not pin anything over the panes that exist
to interrupt (`focus`, `activity`, `live`, `attention`, `alert`). Pinning
those from the couch would amount to switching the rubric off.

The rubric already had a household-settings channel:
[ADR-0011](0011-rubric-settings-on-the-share.md)'s overrides, written through
pub-signals, logged with time and address, and shown on the board.

## Decision

- **A rubric setting, `default.pane`, names the default resting pane.**
  When that pane is live and `ambient`, it ranks first in its rung and holds
  instead of taking turns. Every other class ranks as before, and a default
  that is not on the bus changes nothing. The configurator offers it as a
  dropdown of the live resting panes.
- **Left/Right on the main view writes that setting.** The app cycles the
  line-up's `ambient` items, starting from the one on screen, or from the
  first (the current default) while something urgent is up. It shows each
  candidate at once as a peek with a caption, and about 1.5 s after the last
  press it posts `{"id": "default.pane", "action": "set", "label": <pane>}`
  to pub's `/api/signals/rubric`. A run of presses saves once. Back before
  the save cancels it. The caption then says whether it was saved, and the
  stream follows a few seconds later.
- **Up/Down is unchanged:** it only peeks.

## Consequences

- **The remote now changes what the screen rests on**, through the same
  channel, validation and audit trail as the configurator. Each change is a
  line in `signals/rubric.jsonl` naming the Roku's address, and the board
  lists it under recent changes.
- **Urgent panes keep their power.** A pull-request, pipeline or alert pane
  still takes the screen, and the default returns after it.
- **The default persists** until someone changes it, from the remote or the
  configurator. Clearing it ("None" in the dropdown) puts the resting panes
  back to taking turns, each for its `dwell_s` (the family panes use 60 s).
- **Anyone with the remote can set the default.** That is the same trust as
  the configurator page and as anyone on the LAN. Nothing it sets can hide an
  urgent pane.

## Alternatives considered

- **Left/Right pins any pane, over alerts too.** Rejected: urgent panes could
  go unseen, and the remote would become a second writer of the decision.
- **A remote-only hold that expires.** The setting persists instead, because
  "the new default" is what was asked for, and a timer would quietly undo it.
- **Saving on every press.** The pause before saving keeps the log to one
  line per choice and lets Back cancel.
