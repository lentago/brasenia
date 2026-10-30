# ADR-0011: Rubric settings are household overrides on the share, written through pub-signals

**Status:** Accepted (2026-10-28; #70). The `rotation.dwell_s` setting it
lists was retired with rotation by
[ADR-0020](0020-only-the-rubric-and-the-remote-change-the-wall.md) (#121); an
old override of it is an unknown setting and changes nothing.

## Context

Rubric v1's settings were code constants in `compositor/rubric.py`: the class
priorities (`PRIORITY`) and the default rotation dwell (`DEFAULT_DWELL_S`).
The briefing fallback had no setting at all; it used `brief/index.html`
whatever its age. Changing any of them meant a PR, a merge, and pub's next
pull of `/srv/brasenia`.

The rubric board (#63) made the decision visible and showed a problem worth a
setting: with nothing live, the wall would fall back to a morning brief last
published on 2026-08-31. Chris asked for a web-based configurator, with the
settings on the share alongside the visualizer rather than in git.

Two facts constrain where a page's edits can go. pub serves only static files
except for one write path, `pub-signals` (kalmia#165), which appends small,
bounded JSON lines to `signals/<namespace>.jsonl` on the share. And the fleet's
live-state rule says enforced infrastructure state lives in git.

## Decision

- **Defaults stay in code.** The rubric's code values remain the defaults, and
  the briefing fallback defaults to "any age", so nothing changes until someone
  sets something.
- **Overrides live on the share.** `viewport/configure.html` posts one signal
  per change to `/api/signals/rubric` (namespace and `set` action allowlisted in
  kalmia#176): `set` with the value in `label`, or `undo` to drop the override.
  The log, `signals/rubric.jsonl`, is the record of every change, with its time
  and the address it came from.
- **The compositor applies them.** Each cycle it reads the log, validates each
  entry against `compositor/settings.py`'s spec and applies the latest valid
  one per setting. A rejected value changes nothing and shows on the board. It
  writes the effective settings to `viewport/rubric.json`, beside
  `rubric.html` and `configure.html`.
- **Settings v1:**
  - a priority for each of the six pane classes (1–999);
  - `briefing.max_age_hours`, where 0 turns the fallback off and unset means
    any age;
  - `rotation.dwell_s`, the default dwell (5–600 s).

## Consequences

- **Changes take effect in seconds** and are visible on the board: overridden
  values are marked, recent changes are listed (rejected ones included), and
  the briefing rung says when and why it is skipped.
- **Some live behaviour is no longer in git.** That is deliberate. These are
  household preferences, like the pane claims already on the bus, not
  infrastructure; the signal log is their audit trail, and `rubric.json` is
  their current value. Rubric *code* (what the settings mean) stays in git.
- **Anyone on the LAN can change the rubric**, the same trust as pub-signals'
  other client and as claiming a pane. The settings are bounded (validated
  ranges, a 4 KiB body cap at the sink), so the worst outcome is a strange
  ranking, which is visible on the board and undone from the same page.
- **The compositor reads one more file each cycle.** The log grows by one line
  per change; a human-paced log stays small.

## Alternatives considered

- **Settings in git** (a `rubric.json` in brasenia). Every change is reviewed,
  but editing from a page would need a GitHub credential on pub (ADR-0008 calls
  a producer needing a secret a smell), or else the page could only hand the
  user a snippet to commit.
- **A settings file the page overwrites in place.** pub has no write path for
  that. Adding one would be a second service, with no history, where an
  append-only log already exists.
- **Git defaults plus share overrides, with the overrides periodically folded
  into git.** Possible later, but it adds a reconciliation loop nobody has asked
  for.
