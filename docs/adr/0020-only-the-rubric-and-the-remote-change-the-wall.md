# ADR-0020: Only the rubric and the remote change what the wall shows

**Status:** Accepted (2026-10-29, Chris; #117). Amends
[ADR-0019](0019-panes-on-a-1920x1080-canvas-with-a-30px-floor.md) (a pane is
one band), [ADR-0016](0016-panes-carry-a-revision-and-may-link-a-web-page.md)
(a link pane shows one band, and its `dwell` is ignored),
[ADR-0014](0014-home-and-fleet-feed-resting-panes.md) and
[ADR-0018](0018-standing-slots-are-household-settings.md) (resting panes and
slots no longer take turns), and retires the rubric's rotation (Rubric v1 in
[`concept.md`](../concept.md#rubric-v1)). Builds on
[ADR-0003](0003-rubric-driven-selection-compositor-sole-writer.md) (the
compositor is the only writer to the screen),
[ADR-0012](0012-the-remote-peeks-it-never-decides.md) and
[ADR-0013](0013-the-remote-sets-the-default-resting-pane.md) (what the remote
may do), which stand unchanged. Implementation: lentago/kalmia#223 (renderer),
#118 (one band), #121 (strict order).

## Context

Chris, 2026-10-29: *"I don't want ANY automatic changes outside the rubric
and remote."*

What the wall shows is the compositor's decision (the pointer,
`current.json`), rendered by `brasenia-render` on LXC 118 into one stream that
every Roku mirrors. The remote peeks at other panes without changing anything
(ADR-0012). Its one decision is the household's default resting pane, which
it writes through pub-signals (ADR-0013).

Timers turn up in several places between the bus and the glass. Two of them
changed what is shown without the rubric having made a new decision:

- **Band rotation.** The renderer flipped a multi-band pane's bands into the
  stream every `BRASENIA_BAND_DWELL` seconds (12). The renderer, not the
  rubric, decided which band showed. ADR-0019 allowed a pane 1–4 bands, and
  one live pane used two: `search-map`, published from outside this repo.
- **The rubric's rotation.** When several panes shared the top rung, the
  compositor showed each for its `dwell_s` (the producers set 60 s; the
  household default `rotation.dwell_s` was 20 s), unless the household's
  default resting pane was on top, in which case it held.

## Decision

- **The principle.** What the wall shows changes only when the rubric makes a
  new decision, or a person acts through the remote or the household
  settings (the configurator writes the same settings as the remote,
  ADR-0011). No timer changes it.
- **What counts as a change.** A change of *what is shown* is a different
  pane. These are not changes:
  - **A refresh of the shown pane's content.** A producer rewrites
    `pane.html`, a new `rev` is re-rendered, a link pane renders again every
    `refresh_s`, or a pane without a `rev` is re-rendered.
  - **Playback mechanics** that restore the same picture: the retry handler,
    and the lag guard's rejoin.
  - **The burned-in clock**, which is part of the frame. The pane contract
    reserves its corner.
  - **A stand-in giving way to the decided pane.** When the renderer cannot
    show the pane the rubric chose, it shows a stand-in: the previous image
    after a failed render, or a "this page isn't shown here" notice while
    Chromium's sandbox is down. When the stand-in is replaced by that pane,
    the decision is finally being shown; nothing new was decided.
- **A pane is one band** (Chris, 2026-10-29). Multi-band panes are no longer
  allowed. The renderer shows a pane's single 1920×1080 band (on the
  1280×720 canvas, its single 1280×720 band), and band rotation and
  `BRASENIA_BAND_DWELL` go. A link pane's `source.screens` is fixed at 1, and
  `pane claim --screens` goes. Content that does not fit one band leaves the
  wall. This was the one-band choice already made for the family brief
  (#115). `search-map` is redesigned to fit one band where it is published.
- **There are no ties** (Chris, 2026-10-29: *"There should not be ties."*).
  The rubric ranks the live panes in a strict total order. The first pane in
  it is shown, and nothing rotates. The order is:
  1. priority, highest first (the class's priority, ADR-0011);
  2. the household's default resting pane (ADR-0013);
  3. origin, operator before fleet;
  4. arrival, newest first. Resting (`ambient`) panes skip this step and
     keep a fixed order, so the remote's Left/Right order stays put;
  5. the pane id.

  The pane id is unique on the bus, because it is the pane's directory name,
  so no two live panes can ever rank equal. No setting can produce a tie, and
  no validation is needed to prevent one.

  **Arrival** is when the compositor first saw the pane live. It is kept in
  the compositor's state, and forgotten when the pane stops being live. The
  order must not use `created`: every producer rewrites `created` each cycle,
  because it is the base of the TTL, and `pane renew` resets it too, so ranking
  by it would flip two panes in a rung on the producers' cadence. That would
  be a timer in disguise. A pane that leaves the bus and comes back arrives
  again, which is a new decision.

  A manifest's `dwell_s` is still accepted, for Contracts v1 compatibility,
  and ignored. The household setting `rotation.dwell_s` retires. Within the
  resting rung, the default pane shows, and Left/Right changes it. With no
  default set, the first resting pane by id shows.
- **The peek's 60 s close stays** (Chris, 2026-10-29). It only removes the
  remote's own overlay, and it returns the screen to the rubric's decision.
- **Automation feeding the rubric is allowed, and so is the clock** (Chris,
  2026-10-29): session beacons, `pane claim`, and producers adding or
  removing panes put candidates on the bus, and the rubric decides.

The inventory, every place time changed the wall as of 2026-10-29, with its
verdict:

| # | What | Where | Trigger | Verdict |
|---|---|---|---|---|
| 1 | A multi-band pane's bands flip every 12 s | kalmia `brasenia-render`, `BRASENIA_BAND_DWELL` | timer | **Goes.** A pane is one band (kalmia#223, #118) |
| 2 | Same-rung panes take turns every `dwell_s` (20–60 s) unless the default resting pane holds | `compositor/rubric.py`, `_rotate` | timer inside the rubric | **Goes.** A strict order, no ties (#121) |
| 3 | A new decision: a pane arrives or outranks, its TTL expires, the pointer falls back to the briefing or the status card | compositor, evaluated every 1 s | rubric | Allowed: the rubric |
| 4 | Panes put on the bus or taken off by automation: session beacons (focus panes), `pane claim` by sessions, the pipeline pane, standing slots, `family-today` leaving once the brief is stale | producers, sessions | automation, decided by the rubric | Allowed: rubric inputs (Chris) |
| 5 | Household settings: `default.pane`, priorities, standing slots | remote Left/Right, configurator (ADR-0011, ADR-0013, ADR-0018) | a person | Allowed: the remote and the settings |
| 6 | The shown pane's content refreshes: producers rewrite on their cadence (the family brief every minute, Grafana every `refresh_s`), a new `rev` re-renders, a pane without one re-renders every 60 s, and a link pane every `refresh_s` | producers; renderer `BRASENIA_REGEN_INTERVAL` | timer, same pane | Allowed: content, not a change of what is shown |
| 7 | A failed render is retried after 30 s; a "this page isn't shown here" notice gives way to the page when Chromium's sandbox is back (600 s) | renderer | fault recovery | Allowed: a stand-in giving way to the decided pane |
| 8 | Pointer poll (1 s), line-up poll (10 s) | renderer | follows the decision | Allowed: no change unless the decision changed |
| 9 | The burned-in clock ticks every second | `brasenia-stream` | timer | Allowed: part of the frame (Chris) |
| 10 | Retry after a player error (3 s), rejoin when more than 8 s behind live on two checks 15 s apart | Roku app | playback faults | Allowed: same picture |
| 11 | A peek closes after 60 s with no key press | Roku app `idleTimer` | timer | Allowed: it removes only the remote's overlay (Chris) |
| 12 | An open peek refreshes its image, or closes when its pane leaves the line-up | Roku app | line-up | Allowed: content, or the rubric |
| 13 | Left/Right writes `default.pane` 1.5 s after the last press | Roku app `postTimer` | a press, debounced | Allowed: the remote |
| 14 | pub's `brasenia-update` restarts the viewport services when `main` moves (daily 06:00) | kalmia pub role | deploy | Allowed: the compositor keeps its state across a restart, so nothing shown changes |

## Consequences

- **The renderer stops rotating bands** (lentago/kalmia#223). It renders and
  shows a pane's first band only.
- **The contract becomes one band** (#118). This covers ADR-0019's canvas
  (1080 px tall, no longer up to 4320), the pane contract in `concept.md`,
  `docs/claiming-the-display.md`, `bin/pane claim --screens`, and the
  compositor's validation of `source.screens`. The external `search-map`
  pane is redesigned where it is published.
- **The compositor ranks strictly** (#121). `_rotate`, the rotation cursor,
  `rotation.dwell_s` and `pane claim --dwell` go, and arrival replaces
  `created` in the order.
  Rubric v1 and Contracts v1 in `concept.md` are updated, and so are the
  producers' READMEs that describe taking turns.
- **A resting wall is still.** It shows the default resting pane, or the
  first resting pane by id when no default is set. Left/Right is how the
  household changes it.
- **ADR-0012 and ADR-0013 stand.** The remote still peeks and still sets
  only the default resting pane.

## Alternatives considered

- **Treat a pane's bands as one piece of content**, so flipping them is a
  content refresh. Rejected: what is on the glass changes on a timer the
  rubric never decided, which is exactly what the rule forbids.
- **Let the remote page bands**, for every screen (widening ADR-0013) or as a
  local peek of other bands (ADR-0012's model). Not chosen: nothing in this
  repo needs a second band, and one band per pane is the simplest rule.
- **Keep the rubric's rotation**, which the rule's letter allows because it
  is inside the rubric. Rejected by Chris: there should not be ties.
- **A declared resting order in the household settings**, refused if it
  could produce equal ranks. Not needed: the pane id already makes the order
  strict, and the remote's default resting pane already lets the household
  choose what rests on the wall. It can be added later if the household
  wants to order the rest.
- **Rank by `created`**, as Rubric v1 did for non-resting rungs. Rejected:
  producers renew it every cycle, so a strict order built on it flips panes
  on their cadence.
