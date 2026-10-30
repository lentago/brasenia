# fleet producer (the claytonia job queue → the fleet pane)

**What you're about to do:** run a small stdlib-only Python process (3.11+)
that reads the bullpen's job queue (the `claude-jobs` share) and GitHub's
search API, and keeps one resting pane on the viewport bus:
`<webroot>/viewport/panes/fleet/`. It shows the workers (idle, busy with a
project, or silent), what is waiting, the last day's runs, and the open agent
PRs awaiting review.

**Why bother:** it is one of the positions on the resting-pane ladder
([#86](https://github.com/lentago/brasenia/issues/86)) that the Roku remote's
Left/Right picks the household's default from
([ADR-0013](../../docs/adr/0013-the-remote-sets-the-default-resting-pane.md)).
It is `class: ambient`, so anything urgent still takes the screen.

**Time:** a minute against a copy of the queue or the fixtures. Running it
for real on pub is kalmia's `brasenia-fleet.service`, which reads the queue
through a read-only bind mount at `/srv/claude-jobs`.

## What it shows, and what it never reads

Counts, worker names, project names, models, durations, and PR titles. It
never opens a prompt, a log or a transcript: of a JSON job spec it keeps only
`project` and `model`, and it never opens a plain-text job at all.
[ADR-0014](../../docs/adr/0014-home-and-fleet-feed-resting-panes.md) records
the read-only mount.

## Try it

From `producers/fleet/`, on a machine that mounts the share (the workstation
has it at `/mnt/lentago/claude-jobs`):

```sh
W=$(mktemp -d)
python3 -m fleet_producer --once --webroot "$W" --jobs /mnt/lentago/claude-jobs
ls "$W/viewport/panes/fleet/"
```

Options: `--jobs` (default `/srv/claude-jobs`), `--tz` (default
`America/New_York`), `--interval` (default 60 s), `--once`, `--now`.

## How you know it worked

- `panes/fleet/` holds `pane.html` and `manifest.json`, and no `.partial`
  files. The manifest reads `class: ambient`, `ttl_minutes: 10`,
  `dwell_s: 60`, `author: fleet-producer@pub`, `origin: operator`.
- At 1920×1080 the page shows five counts (workers alive, busy, waiting, runs
  and failures in the last 24 hours) over three cards: Workers, Last 24 hours
  (the six newest runs) and Agent PRs to review (oldest first). The
  bottom-right corner is empty, kept clear for the clock.
- The tests pass: `python3 -m unittest discover -s tests`.

## How it works

Each cycle (every 60 s) reads the queue the way claytonia's own tools do
(`bin/cr-submit`'s occupancy probe):

- **Workers**: `workers/<host>.alive` is a heartbeat; a worker is alive while
  it is at most 90 s old. One older than that but under a day is shown as
  silent. Older ones are retired and left off.
- **Busy**: `processing/<runid>.owner` (`owner=`, `started=`, `origname=`)
  beside its job file, held by a live worker. A dead owner's claim is the
  reaper's, not busy.
- **Waiting**: `inbox/` entries, skipping what process-inbox never claims
  (`.*`, `*.partial`, `*.tmp`, `*.swp`, `*.owner`).
- **Runs**: `logs/<runid>.meta`, opened only for runids that started in the
  last 26 hours (the runid begins with its UTC start time), and kept when
  `finished` falls in the last 24. A finished `.meta` never changes, so it is
  parsed once.

Agent PRs come from one search, `is:pr is:open
author:app/lentago-claude-runner`, without a token, every 5 minutes. Search
has its own rate limit (10 a minute), apart from the focus producer's core
budget. A failed search keeps the last list, and the header says how old it
is. Unauthenticated search sees public repositories only.

If the queue isn't there (no mount), the cycle changes nothing and the pane
leaves the bus at its 10-minute TTL. Files are written `x.partial` then
renamed, `manifest.json` last. A pane directory with another author's
manifest is left alone.

## Tests

```sh
python3 -m unittest discover -s tests
```

They build a made-up queue in temp directories (heartbeats aged with
`os.utime`, claims, an inbox, `.meta` files) and use a fake search, with no
network. CI runs them on 3.11 and 3.12
(`.github/workflows/fleet-producer-tests.yml`, informational, never a
required check).
