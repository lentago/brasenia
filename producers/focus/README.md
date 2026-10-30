# focus producer (session beacons → open-PRs panes)

**What you're about to do:** run a small stdlib-only Python process
(3.11+) that watches the session beacons on the viewport bus and, for every
repo with a fresh beacon, keeps a pane on the bus showing that repo's open
pull requests. It reads `<webroot>/viewport/focus/*.json` and writes
`<webroot>/viewport/panes/focus-<owner>-<name>/{pane.html,manifest.json}`.

**Why bother:** this is the "the work is the claim" half of the focus pane
([#26](https://github.com/lentago/brasenia/issues/26)). A session working in a
repo already beats every 30 s; this turns that beat into something worth
glancing at (the PRs in flight, their checks and reviews, whether `main` is
green) without anyone claiming the screen by hand. When the session goes
quiet, the pane goes away. The compositor
([#27](https://github.com/lentago/brasenia/issues/27)) decides whether it
shows; this process only puts it on the bus.

**Time:** a minute to try it against a scratch directory (below). Running it
for real on pub is a kalmia unit
([kalmia#140](https://github.com/lentago/kalmia/issues/140)), not something
this repo deploys.

## Try it

From `producers/focus/`:

```sh
W=$(mktemp -d) && mkdir -p "$W/viewport/focus"
printf '{"schema":1,"host":"thinkpad","session":"19ca7047","repo":"lentago/brasenia","cwd":"/x","origin":"operator","ts":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$W/viewport/focus/thinkpad-19ca7047.json"
python3 -m focus_producer --webroot "$W" --once
ls "$W/viewport/panes/focus-lentago-brasenia/"
```

Options: `--url-base` (default `http://pub.lan`, where `pipeline.json` is
read from), `--interval` (default 30 s), `--tz` (default `America/New_York`,
the zone of the pane's clock times; pub itself runs in UTC), `--once` (one
cycle, then exit).
Logs go to stdout, which is the journal under systemd.

## How you know it worked

- `panes/focus-lentago-brasenia/` holds `pane.html` and `manifest.json`,
  and no `.partial` files, as long as the repo has something to show: an
  open PR, a `main` run that didn't pass, or a pipeline row. A quiet repo
  gets no pane (see below), so try it with a repo that has an open PR.
- Opening `pane.html` in a browser at 1920×1080 shows the repo name, its open
  PRs (number, title, author, age, draft flag, check state, review
  decision), `main`'s latest push run, and a "data as of HH:MM" stamp
  bottom-left. The bottom-right corner is empty, kept clear for the clock.
- Delete the beacon and run `--once` again: the pane directory is gone.
- The tests pass: `python3 -m unittest discover -s tests`.

## How it works

Each cycle:

1. Reads every `viewport/focus/*.json` beacon. Beacons whose `ts` is more
   than 10 min old, or that don't parse, are deleted. The rest are grouped
   by `repo`; a null `repo` is ignored.
2. For each repo, fetches its open PRs, each PR's check runs and reviews,
   and `main`'s latest meaningful push run, that is, the newest of the last
   five completed runs that a push to `main` triggered and that did not end
   as `skipped`, `neutral` or `cancelled` (one request), from the GitHub REST API,
   unauthenticated. Reads `<url-base>/viewport/pipeline.json` once per cycle;
   a missing or unreadable file means no pipeline row.
3. Writes `pane.html`, then `manifest.json`, each as `x.partial` renamed to
   `x`. `created` is set to the cycle time, so the 10-min TTL slides while
   beacons stay fresh. `origin` is `operator` if any fresh beacon for the
   repo is `operator`, otherwise `fleet`.
4. Removes every `focus-*` pane directory that no fresh beacon maps to.
   Directories without the `focus-` prefix, and `focus-*` directories whose
   manifest names a different `author`, are never touched.

The pane id is `focus-` plus the repo lowercased, with every character
outside `[a-z0-9]` turned into `-`: `lentago/.github` →
`focus-lentago--github`.

**Main's run** is the newest of the last five completed push-event runs on
`main` (workflow runs that a push to `main` triggered, as opposed to runs that
an issue or pull-request comment triggered) whose conclusion is not `skipped`,
`neutral` or `cancelled`, so a skipped comment-triggered workflow doesn't mask
the real state. When none qualifies the pane says `main: no push run`.

**Quiet repos get no pane.** A beaconed repo with no open pull requests, a
`main` run that passed (`success`, `skipped` or `neutral`) or no push run at
all, and no pipeline row has nothing worth the screen, and a `focus` pane
would still outrank the household's resting surface. So the producer writes
nothing for it, and removes its own pane if one is up; the pane returns on
the first cycle where any of that changes. A GitHub failure never counts as
quiet: the previous pane is kept, as below.

**Check state** folds the head commit's check runs: any failed, cancelled or
timed-out run is `failing`, otherwise any unfinished run is `pending`,
otherwise `passing`; no runs is `none`. Legacy commit statuses aren't read.
**Review decision** is derived from the reviews list, since the REST API has
no `reviewDecision`: each reviewer's latest approve / request-changes /
dismiss counts, so a PR shows `changes requested`, `approved`,
`review requested` or `no review`.

### Request budget

Unauthenticated GitHub allows 60 requests an hour per IP. Requests carry the
stored ETag (`If-None-Match`), but an unauthenticated 304 still costs one
request: measured 2026-10-07, `x-ratelimit-remaining` drops on every 304.
GitHub exempts 304s only for authorized requests. A refresh costs
`2 + 2 × open PRs` requests, so with one or two open PRs, one refresh a
minute uses up the hour's budget in 10 to 15 minutes.

So each repo's data is held for at least 60 s and, beyond that, long enough
that all active repos together spend at most 50 requests an hour:
`hold = 3600 × cost × active repos / 50`. One repo with two open PRs
refreshes every 7 min 12 s; the "data as of" stamp shows how old the data
is. The pane and manifest are still rewritten every cycle. No refresh
starts when the server reports fewer requests left than it needs.

### Failure behaviour

| Case | What happens |
|---|---|
| GitHub network error, 403 rate limit, 5xx, or too little budget left | The previous `pane.html` is kept; only its stamp is rewritten to `data as of HH:MM · GitHub unavailable, last tried HH:MM`. The manifest is refreshed, so the pane stays live. Logged; the next cycle retries. |
| Same, with no previous `pane.html` | Nothing is written for that repo this cycle. |
| `pipeline.json` missing or unreadable | The pipeline row is left out. |
| A beacon that doesn't parse | Deleted. |

## The pane

One 1920×1080 band, self-contained: inline CSS, no scripts, no external
assets. Dark background `#0e2b1a`, text `#f3f0e8`, muted `#cdd6d0`, one
accent `#E0A81C` (repo name, failing checks, change requests, a non-green
`main`). Text is 30 px or larger, inside 36 px margins. The layout is fixed
height: at most nine PR rows, then `+N more`. Content stops 111 px above the
bottom edge, and the stamp ends 384 px short of the right edge, so the
bottom-right 330×75 px clock corner stays clear.

The pane contract, manifest and beacon shapes are the v1 contracts in
[`docs/concept.md`](../../docs/concept.md) (written there by #27).

## Tests

```sh
python3 -m unittest discover -s tests
```

They run against a fake GitHub transport and temp directories: beacon
grouping and staleness, pane id mapping, ETag reuse and request pacing,
rendering (band height, the clock corner, no external references), a
failure keeping the old pane, and cleanup of orphaned panes. CI runs them
on 3.11 and 3.12 (`.github/workflows/focus-producer-tests.yml`,
informational, never a required check).
