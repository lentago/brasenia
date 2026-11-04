# PRs producer (GitHub → the PRs pane)

*Written with Claude Code (Anthropic), like the rest of this repository: see
the [README](../../README.md).*

**What you're about to do:** run a small stdlib-only Python process (3.11+)
that reads GitHub's search API and keeps one resting pane on the viewport bus:
`<webroot>/viewport/panes/prs/`. It shows the fleet's pull requests as a
running list, newest event first, with each one's merge status: open, draft,
merged, or closed without merging. With pub's public-read-only GitHub token
([ADR-0021](../../docs/adr/0021-a-public-read-only-github-token-on-pub.md)),
each open row also says what it waits on: failing checks, auto-merge armed,
the AI review, or running checks
([#137](https://github.com/lentago/brasenia/issues/137)). Without the token it
runs as before, minus that column.

**Why bother:** the other panes each show a slice of the PR traffic. `focus-*`
shows the open PRs of a repo a session is working in, `fleet` shows the
bullpen's agent PRs awaiting review, and `change-pipeline` shows a change only
while it travels to live. This pane shows the whole org at a glance: what just
merged, what was just opened, and what was closed without merging
([#134](https://github.com/lentago/brasenia/issues/134)). It is a resting pane
(`class: ambient`), so the Roku remote's Left/Right can make it the default
([ADR-0013](../../docs/adr/0013-the-remote-sets-the-default-resting-pane.md)),
and anything urgent still takes the screen.

**Time:** a minute to try it against a scratch directory (below). Running it
for real on pub is a kalmia unit (`brasenia-prs.service`, beside
`brasenia-fleet.service`), not something this repo deploys.

## Try it

From `producers/prs/`:

```sh
W=$(mktemp -d)
python3 -m prs_producer --once --webroot "$W"
ls "$W/viewport/panes/prs/"
```

That run has no token, so the open rows show authors and the footer says "no
GitHub token". To see the state column, hand it your own `gh` token through a
file descriptor, so the token is never written to disk:
`python3 -m prs_producer --once --webroot "$W" --token-file <(gh auth token)`.

Options: `--token-file` (default `$CREDENTIALS_DIRECTORY/github-token` under
systemd, where kalmia's unit loads `/etc/brasenia/github-token`; read once at
start, since systemd copies the credential only when the unit starts),
`--scope` (the search qualifier naming the repos, default `org:lentago`),
`--tz` (default `America/New_York`, for clock times and where "today" starts;
pub itself runs in UTC), `--interval` (default 60 s), `--once` (one cycle,
then exit), `--now` (pretend the clock reads this RFC 3339 time). Logs go to
stdout, which is the journal under systemd.

## How you know it worked

- `panes/prs/` holds `pane.html` and `manifest.json`, and no `.partial`
  files. The manifest reads `class: ambient`, `ttl_minutes: 10`,
  `author: prs-producer@pub`, `origin: operator`, `title: Pull requests`.
- At 1920×1080 the page shows three counts (open now, opened today, merged
  today) over the running list: ten rows, each with a status chip, the repo,
  the number, the title, who opened it and when. "GitHub search · as of
  HH:MM" sits bottom-left; the bottom-right corner is empty, kept clear for
  the clock.
- With the token, the open rows show a coloured state word where the author
  would be. Without it the rows show authors and the footer adds "· no GitHub
  token". On pub, `journalctl -u brasenia-prs` says "no GitHub token at …" at
  start when the file is empty, and "GitHub refused the token" once if GitHub
  answers 401.
- `../../bin/pane --bus "$(mktemp -d)" claim t --class ambient --ttl 5 --title t "$W/viewport/panes/prs/pane.html"`
  accepts the page (no `<script src=`, `<link href=` or `src="http`).
- The tests pass: `python3 -m unittest discover -s tests`.

## How it works

Each cycle (every 60 s) rewrites the pane, so the times on it stay current.
Every 2 minutes a refresh makes four searches:

1. **The running list:** `org:lentago is:pr`, the 50 most recently updated,
   sorted by each PR's event time, newest first. The event is the merge for
   a merged PR, the close for one closed without merging, and the opening
   for an open PR or a draft. An event is never later than the PR's
   `updated_at`, so the newest events are among those 50 unless more than 50
   PRs were touched since without an event (a comment, a push).
2. **Three counts,** each the `total_count` of a one-item search:
   `is:open`, `created:>=` local midnight, and `merged:>=` local midnight.

Every `lentago` repository is public, so search without a token sees the
whole org. Search has its own rate limit (10 requests a minute without a
token), apart from the 60-an-hour core budget the focus producer paces itself
against. Two searches a minute here and the fleet producer's one every five
minutes stay well inside it.

Search results carry no check state, auto-merge or review. With the token,
each good refresh reads them for the open, non-draft rows among the ten on
the pane, in one GraphQL query by node id (search items carry each PR's
`node_id`):

- **checks:** the head commit's `statusCheckRollup`: `SUCCESS` passing,
  `FAILURE` or `ERROR` failing, `PENDING` or `EXPECTED` running, none when
  the commit has no checks;
- **armed:** `autoMergeRequest` is set;
- **reviewed:** among the first 50 and the last 50 comments, one that opens
  with a "Review (" heading, posted by `github-actions` (claude-review.yml's
  "## Review (haiku, claude-review.yml)") or by the repo's owner, a member or
  a collaborator ("Review (Haiku, local)" where a repo has no caller, .github
  ADR-0013). The
  soft-fail notice ("could not complete") is not a review. A `re-review` or
  `review:sonnet` label means a fresh review is still to come, since the
  caller removes the label after its run, so the row reads "awaiting
  review" again.

An open row shows the first that applies, in place of its author:

| Word | Colour | When |
|---|---|---|
| checks failing | red | a check on the head commit failed, armed or not |
| armed | green | auto-merge is armed: it merges when the required checks pass |
| awaiting review | amber | no review has posted (or a re-review is asked for) |
| checks running | blue | reviewed, not armed, checks still running |
| reviewed | white | reviewed, checks passing or none, not armed: a person triages and arms it |

Drafts keep their author: the reviewer skips them and they can't be armed. A
row whose state is unknown (no token, a new PR the last query didn't cover,
or a state older than 15 minutes) shows its author too.

### The token and the request budget

The token is sent on every read, searches included
([ADR-0021](../../docs/adr/0021-a-public-read-only-github-token-on-pub.md)).
It is never logged or put in a URL. Per hour, at the 2-minute refresh:

| Reads | Per hour | Budget it draws on |
|---|---|---|
| Searches: 4 a refresh | 120 | Search's own limit: 30 a minute with the token, 10 without. Not the hourly 5,000. |
| GraphQL state query: 1 a refresh, at most 10 PRs | 30 queries, 30 points (each costs 1) | The token owner's 5,000 GraphQL points an hour, shared with `gh` on the workstation |

ADR-0021 gives this pane at most 200 an hour of core requests and GraphQL
points together. It makes no core requests, and it enforces the 200 itself
(`STATE_BUDGET`): it adds up what each state query cost over the last hour,
from GraphQL's `rateLimit.cost`, and starts no query once the total
reaches 200. It also starts none while the last answer's `x-ratelimit-remaining` is below
1,000 (`LOW_REMAINING`), until that window resets, so in a busy hour the wall
falls back to staler state before the workstation's sessions run short.

**Times** in the list read "now" or "N min" within the hour, then the clock
time today ("5:01 PM"), the weekday within the week ("Sun"), and the date
before that ("Oct 24"), all in `--tz`.

**Names:** the bullpen's GitHub App (`lentago-claude-runner[bot]`) shows as
`bullpen`; any other `[bot]` suffix is dropped (`dependabot`).

### Failure behaviour

| Case | What happens |
|---|---|
| A search fails: network error or truncated response, rate limit (403/429), 5xx or an unexpected body | The whole refresh is dropped and the last good data kept. The pane is still rewritten each cycle, with "GitHub unavailable, last tried HH:MM" in the header, and the footer keeps the data's own time. Logged; the next refresh retries in 2 minutes. |
| No token: the file is missing or empty (kalmia's role creates it empty) | Searches run anonymously and no state query is made. The open rows show authors, and the footer adds "· no GitHub token". Logged once, at start. |
| GitHub answers 401 (the token expired or was revoked) | The token is dropped for the rest of the run, logged once, and the search repeated without it. From then on, as for no token. A new token takes effect when the unit restarts, which seeding does. |
| The state query fails: network, 5xx, an unexpected body | The list is still written. The last good state for each row is kept until it is 15 minutes old, then the row shows its author. Logged; retried at the next refresh. |
| GraphQL's `x-ratelimit-remaining` below 1,000 | No state query until the window resets. The footer adds "· PR state paused, rate limit low", and state already read stays for up to 15 minutes. Logged once a pause. |
| This hour's state queries have cost 200 points | No state query until the oldest cost leaves the hour. Logged. At one point a query every 2 minutes this never happens; it guards against a query priced higher than expected. |
| No good refresh yet | Nothing is written. |
| The last good data is more than 15 minutes old | The pane is no longer renewed, so it leaves the bus at its 10-minute TTL rather than showing an old list. That follows [ADR-0014](../../docs/adr/0014-home-and-fleet-feed-resting-panes.md)'s rule that a resting pane whose source goes quiet leaves the bus; the 15 minutes is this producer's own threshold (`STALE_S`), seven missed refreshes. It returns on the next good refresh. |
| `panes/prs/` holds another author's manifest | Left alone; logged. |

## The pane

One 1920×1080 band, self-contained: inline CSS, no scripts, no external
assets. Dark background `#0f1518` and cards `#172025`, as on the fleet pane,
with a green header band `#1d3a33`. The status chips use GitHub's colours:
green `#3fb950` open, grey `#8b949e` draft, purple `#a371f7` merged and red
`#f85149` closed. The state words use red `#f85149`, green `#3fb950`, amber
`#f0a53a`, blue `#58a6ff` and white `#e4ebee`, at 30 px in the 245 px
author column, which fits "awaiting review" (237 px in DejaVu Sans). Text is 30 px or larger, inside 36 px margins. The layout
is fixed height: a 90 px header, 144 px counts and a 663 px list of ten
57 px rows fill the 933 px main area, which ends 111 px above the bottom
edge. The footer ends 534 px short of the right edge, so the bottom-right
330×75 px clock corner stays clear.

The pane contract and manifest shape are the v1 contracts in
[`docs/concept.md`](../../docs/concept.md).

## Tests

```sh
python3 -m unittest discover -s tests
```

They run against a fake GitHub (search and GraphQL) and temp directories, with
no network: parsing each status and its event time, the four queries and
local midnight, the failure cases, refresh pacing, a failed refresh keeping
the last list, stale data left to its TTL, someone else's pane left alone,
and the render (the contract checks, the rows, the ten-row cap, escaping).
For the token and the state: the token on every read and never in a log, a
401 dropping it once, reading the empty file the role seeds, the checks,
auto-merge and review mapping (CI and local reviews, the soft-fail notice, an
outsider's comment, a re-review label), the precedence of the state words,
only the rows on the pane asked for, stale state dropped, the low-budget
pause and the 200-point hour. CI
runs them on 3.11 and 3.12 (`.github/workflows/prs-producer-tests.yml`,
informational, never a required check).
