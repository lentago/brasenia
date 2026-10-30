# ADR-0018: Standing slots are household settings, kept on the bus by a producer

**Status:** Accepted (2026-10-29; #97). Builds on
[ADR-0011](0011-rubric-settings-on-the-share.md) (household settings on the
share) and [ADR-0016](0016-panes-carry-a-revision-and-may-link-a-web-page.md)
(link panes).

## Context

ADR-0016 let a pane name a web page instead of shipping `pane.html`. A session
can claim one for a while (`pane claim --url`). The household also wants pages
that stay up as part of the resting rotation, chosen from the couch or the
configurator, not from a shell: a dashboard of open pull requests, or a status
page. Changing which pages those are should take seconds and need no pull
request, the same latency the household already has for the rubric's own
settings.

## Decision

- **Each standing slot is one household setting, `link.<pane-id>`**, in the
  rubric's settings channel (ADR-0011).
  - **The value:** a JSON object in the signal's `label`, the slot's `title`
    plus a link pane's `source` fields.
  - **Changes:** `set` adds or changes the slot and `undo` removes it. Each
    change is a logged line naming who sent it, like every other setting, and
    the board's history shows it.
  - **Validation:** the compositor validates the value with the same rules as
    a manifest `source`, so a bad slot is rejected there and changes nothing.
- **The configurator lists the slots** with a Remove button each, and has a
  form to add one. pub-signals caps a label at 500 characters, which bounds a
  slot's URL to roughly 400.
- **A producer, `producers/links`, keeps a link pane on the bus for each
  slot.**
  - **Input:** the validated slots in `viewport/rubric.json`, not the signal
    log.
  - **The panes:** one `ambient` pane each, author `links-producer@pub`,
    renewed every 30 s with a 10-minute TTL. It removes its own pane when the
    slot goes, and never touches a pane another author owns.
- **Slots are resting panes.** They rotate with the other `ambient` panes, the
  remote's Left/Right steps through them and can make one the default, and
  anything urgent still takes the screen.

## Consequences

- **Adding or removing a slot reaches the bus in about 30 s**, and the screen
  shortly after (once link panes are on).
- **The compositor stays a ranker.** Slots arrive on the bus as panes, so the
  board, the line-up, `pane ls` and the peek treat them like any other pane.
  This follows the fleet's rule that a new source is a new client, not a
  change to the core.
- **The producer needs its own unit on pub**, which comes from kalmia, like
  the other producers.
- **Anyone on the LAN can add a slot**, the same trust as the rest of the
  configurator. Adding one only writes a setting and, through the producer, a
  manifest. What reaches the screen is decided by three later gates, each
  independent of the others:
  1. **The compositor** points at link panes only with `--link-panes`.
     Without it they wait on the board as `off`.
  2. **The renderer on LXC 118** renders a site other than pub.lan only while
     Chromium runs sandboxed and the host is in `brasenia_allowed_sites`
     (lentago/kalmia#201, #205). A refused page is shown as a notice.
  3. **The URL itself** must carry no credentials. The compositor refuses a
     user or password, and query or fragment parameters that usually carry a
     secret (`token`, `signature`, `key`, …), because the slot's URL is
     published in files anyone on the LAN can read. That is a heuristic, so a
     slot's URL must be token-free by rule.

  The producer does not check the compositor's flag. Writing a manifest is
  harmless, and keeping the producer ignorant of the flag keeps the two
  independent.

## Alternatives considered

- **The compositor turns slots into panes itself**, with no producer.
  Rejected: it puts a source into the ranker and leaves slots invisible to
  everything that reads the bus. It also has no natural TTL, because a slot
  lives until it is removed.
- **Slots in a file in git.** Rejected: every change would be a pull request
  and a deploy, which defeats the point.
- **One setting holding the whole list.** Rejected: a single 500-character
  label cannot hold several URLs, and per-slot keys give each change its own
  line in the history.
