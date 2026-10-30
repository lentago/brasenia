# ADR-0020: Only the rubric and the remote change what the wall shows

**Status:** Proposed (2026-10-29; #117). **Not accepted until Chris decides
the open questions below.** Nothing here is implemented, and the
implementation issues (lentago/kalmia#223, #118) wait for acceptance.
Builds on [ADR-0003](0003-rubric-driven-selection-compositor-sole-writer.md)
(the compositor is the only writer to the screen),
[ADR-0012](0012-the-remote-peeks-it-never-decides.md) and
[ADR-0013](0013-the-remote-sets-the-default-resting-pane.md) (what the
remote may do).

## Context

Chris, 2026-10-29: *"I don't want ANY automatic changes outside the rubric
and remote."*

What the wall shows is the compositor's decision (the pointer,
`current.json`), rendered by `brasenia-render` on LXC 118 into one stream that
every Roku mirrors. The remote peeks at other panes without changing anything
(ADR-0012). Its one decision is the household's default resting pane, which
it writes through pub-signals (ADR-0013).

Timers turn up in several places between the bus and the glass. Two of them
change what is shown without the rubric having made a new decision:

- **Band rotation.** The renderer flips a multi-band pane's bands into the
  stream every `BRASENIA_BAND_DWELL` seconds (12). The renderer decides which
  band shows, not the rubric. One live pane uses it today, `search-map`
  (2 bands), published from outside this repo. ADR-0019 allows a pane 1–4
  bands. Separately, Chris decided on 2026-10-29 that the family brief's move
  to the 1920×1080 canvas (#115) uses one band per pane, with no alternating
  bands. That decision is recorded on #115; it is not yet part of any ADR.
- **The rubric's own rotation.** When several panes share the top rung, the
  compositor shows each for its `dwell_s` (the producers set 60 s; the
  household default `rotation.dwell_s` is 20 s), unless the household's
  default resting pane is on top, in which case it holds. That timer is
  inside the rubric, so the rule's letter allows it and its spirit may not.

## Decision (proposed)

- **The principle.** What the wall shows changes only when the rubric makes a
  new decision, or a person acts through the remote or the household
  settings (the configurator writes the same settings as the remote,
  ADR-0011). No timer outside the rubric changes it.
- **What counts as a change.** A change of *what is shown* is a different
  pane, or a different band of the same pane. These are not changes:
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
- **Band rotation goes.** The renderer stops flipping bands on a timer. What
  replaces it is open question 1.
- **The inventory**, every place time changes the wall today:

| # | What | Where | Trigger | Verdict |
|---|---|---|---|---|
| 1 | A multi-band pane's bands flip every 12 s | kalmia `brasenia-render`, `BRASENIA_BAND_DWELL` | timer | **Violates.** Goes; see question 1 |
| 2 | Same-rung panes take turns every `dwell_s` (20–60 s) unless the default resting pane holds | `compositor/rubric.py`, `_rotate` | timer inside the rubric | **For Chris**, question 2 |
| 3 | A new decision: a pane arrives or outranks, its TTL expires, the pointer falls back to the briefing or the status card | compositor, evaluated every 1 s | rubric | Allowed: the rubric |
| 4 | Panes put on the bus or taken off by automation: session beacons (focus panes), `pane claim` by sessions, the pipeline pane, standing slots, `family-today` leaving once the brief is stale | producers, sessions | automation, decided by the rubric | Allowed as rubric inputs. **Chris to confirm**, question 4 |
| 5 | Household settings: `default.pane`, priorities, `rotation.dwell_s`, standing slots | remote Left/Right, configurator (ADR-0011, ADR-0013, ADR-0018) | a person | Allowed: the remote and the settings |
| 6 | The shown pane's content refreshes: producers rewrite on their cadence (the family brief every minute, Grafana every `refresh_s`), a new `rev` re-renders, a pane without one re-renders every 60 s, and a link pane every `refresh_s` | producers; renderer `BRASENIA_REGEN_INTERVAL` | timer, same pane | Allowed: content, not a change of what is shown |
| 7 | A failed render is retried after 30 s; a "this page isn't shown here" notice gives way to the page when Chromium's sandbox is back (600 s) | renderer | fault recovery | Allowed: a stand-in giving way to the decided pane |
| 8 | Pointer poll (1 s), line-up poll (10 s) | renderer | follows the decision | Allowed: no change unless the decision changed |
| 9 | The burned-in clock ticks every second | `brasenia-stream` | timer | Allowed: part of the frame. **Chris to confirm**, question 4 |
| 10 | Retry after a player error (3 s), rejoin when more than 8 s behind live on two checks 15 s apart | Roku app | playback faults | Allowed: same picture |
| 11 | A peek closes after 60 s with no key press | Roku app `idleTimer` | timer | **For Chris**, question 3 |
| 12 | An open peek refreshes its image, or closes when its pane leaves the line-up | Roku app | line-up | Allowed: content, or the rubric |
| 13 | Left/Right writes `default.pane` 1.5 s after the last press | Roku app `postTimer` | a press, debounced | Allowed: the remote |
| 14 | pub's `brasenia-update` restarts the viewport services when `main` moves (daily 06:00) | kalmia pub role | deploy | Allowed: the compositor keeps its state across a restart, so nothing shown changes |

## Open questions, for Chris's decision

1. **Band paging.** With the 12 s rotation gone, how does anyone see a pane's
   second band?
   - **A. Panes are one band.** The contract drops multi-band panes. The
     renderer shows band 1, link panes' `screens` is fixed at 1, and
     `pane claim --screens` goes. This is the simplest, and it is the choice
     Chris already made for the family brief. `search-map` has to fit one band.
   - **B. The remote pages bands for everyone.** A key (Fast-forward or
     Rewind, say) moves the shown pane to its next band. This writes a
     household setting through pub-signals the way Left/Right does, and it
     changes both screens. It widens the remote's one decision (ADR-0013),
     and needs a rule for when the band resets (a new pane, a new decision).
   - **C. The remote peeks at other bands.** The stream always shows band 1.
     A key overlays the pane's other bands as peek images on the Roku that
     pressed it and changes nothing else, which is ADR-0012's model. The
     renderer writes a peek image per band, and the app learns to step
     through them.

   Recommendation: **A** now, since nothing in this repo needs more than one
   band. Adopt C later if a pane earns a second band.
2. **The rubric's rotation (`dwell_s`).**
   - **Keep it.** It is the rubric, and setting a default resting pane
     already stops it for resting panes.
   - **Hold instead.** The top-ranked pane holds until the rubric's decision
     changes (a pane arrives, outranks or expires), and the remote's
     Left/Right chooses among resting panes. `dwell_s` and
     `rotation.dwell_s` retire.
   - **Hold for resting panes only**, and keep turns for the higher rungs
     (focus, attention).

   Recommendation: **hold**, the reading closest to "no automatic changes".
   It makes Left/Right the way to change a resting wall, which is what the
   remote already does.
3. **The peek's 60 s close.** Keep it (recommended): a forgotten peek
   otherwise covers the wall indefinitely, and closing returns the screen to
   the rubric's decision. Or remove it, so a peek stays until Back.
4. **Confirm the allowed items:**
   - automation feeding the rubric (item 4). Sessions and producers put
     panes on the bus, and the rubric decides whether they show; that is the
     product's premise (ADR-0003).
   - the ticking clock (item 9).

## Consequences

- **The renderer stops rotating bands** (lentago/kalmia#223). Under A, the
  contract surfaces that allow more than one band become one band (#118).
  ADR-0019's "1–4 bands" is then amended, and the external `search-map` pane
  fits one band (tracked where it is published).
- **If question 2 is decided as "hold",** that is a rubric change in
  `compositor/rubric.py`, the household settings, the configurator and the
  concept doc's Rubric v1. Its issue is filed once Chris decides.
- **ADR-0012 and ADR-0013 stand under A and C.** Under B, ADR-0013 is
  amended to give the remote a second decision.

## Alternatives considered

- **Treat a pane's bands as one piece of content**, so flipping them is a
  content refresh (item 6). Rejected: what is on the glass changes on a
  timer the rubric never decided, which is exactly what the rule forbids.
- **Move band rotation into the rubric** (a band index in the pointer,
  advanced by `dwell_s`). That satisfies the letter by moving the timer inside
  the rubric, and fails the spirit. Folded into question 2.
