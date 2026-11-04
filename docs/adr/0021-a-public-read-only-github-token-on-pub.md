# ADR-0021: The PRs and focus producers share a public-read-only GitHub token on pub

**Status:** Accepted (2026-11-04, Chris; #136). Amends
[ADR-0014](0014-home-and-fleet-feed-resting-panes.md): a third credential on
pub, a GitHub token, shared by the prs and focus producers.

## Context

Two producers on pub read GitHub, and today both do it without a token:

- **The PRs pane** ([`producers/prs/`](../../producers/prs/), #134) lists
  the org's pull requests from GitHub's search API. Search results carry no
  check state, auto-merge or review, which come from the core API, one
  request or two for each open PR. Chris chose (option A, 2026-11-02) to
  ship the pane without a token (#135) and add that column later through
  this ADR (#137).
- **The focus producer** ([`producers/focus/`](../../producers/focus/))
  reads each beaconed repo's open PRs, their check runs and reviews, and
  `main`'s latest run. Without a token GitHub allows 60 requests an hour per
  IP, and an unauthenticated 304 still costs one (#31, measured
  2026-10-07). So the producer paces itself to 50 an hour, and one repo with
  two open PRs refreshes every 7 minutes. On 2026-11-04 nine repos had
  beacons up at once.

Every `lentago` repository is public, so a token adds no access. It adds
budget: an authenticated caller gets 5,000 requests an hour, and a 304 to
an authorized conditional request does not count against it [1][2].

ADR-0014 narrowed ADR-0008's "no secrets on producers" to "no secrets
without an ADR". ADR-0017 used that rule for the Grafana token. This ADR
records the GitHub token in the same way. On 2026-11-04 Chris chose a
90-day expiry and asked that the focus producer share the token, which #136
had first left out of scope.

## Decision

- **One fine-grained personal access token, read-only on public
  repositories, with no other permissions.** Chris mints it on his own
  account, with the resource owner set to his user, repository access set to
  public repositories, and no repository or account permissions. Every
  fine-grained token can read public repositories [3], so that read access is
  the token's whole grant. Name it `brasenia pub`.

- **It expires after 90 days** (Chris, 2026-11-04). A rotation mints a new
  token and seeds it as below. The seeding date and the expiry go in the
  rotation's record in kalmia's `docs/pub.md`, so the next rotation date is
  written down.

- **It lives on pub alone, in `/etc/brasenia/github-token`**, a root-only
  file loaded with `LoadCredential=github-token:/etc/brasenia/github-token`
  into two units: `brasenia-prs.service` and `brasenia-focus.service`. No
  other unit loads it. It is never in git, on the share, in a URL, in a log
  or on a page, as with the Home Assistant and Grafana tokens. The display
  guest (LXC 118) stays credential-free.

- **It is seeded by hand, from Chris's own terminal**, with the same
  `read -rsp` command that seeds the Home Assistant and Grafana tokens
  (kalmia `docs/pub.md`). The token never passes through an agent, a chat, a
  shell history or the share. Both units restart afterwards, because
  `LoadCredential=` copies the file only when a unit starts.

- **Without the token, both producers run as they do today.** When the file
  is missing or empty, or GitHub answers 401 (expired or revoked), each
  producer logs it once and falls back to anonymous reads for the rest of its
  run. The PRs pane then drops the state column (#137) and its footer reads
  "no GitHub token", so a lapsed token shows on the wall and not only in the
  journal. The focus producer goes back to its 50-an-hour pacing. Neither
  pane fails or leaves the bus because the credential is missing. systemd
  will not start a unit whose `LoadCredential=` path is absent, so
  lentago/kalmia#280 decides how the units start before the first seed. One
  way: the role creates an empty root-only file once and never overwrites
  it.

- **The wall takes at most a fifth of the hour's budget.** A personal
  token's requests count against the owner's one personal limit, which his
  other tokens and the apps acting for him share [1]. On this workstation
  that is the `gh` CLI that every local session uses. At about 16:07Z on
  2026-11-04, 559 of the 5,000 in the window from 15:28Z to 16:28Z were
  already spent. So:
  - the focus producer spends at most 800 core requests an hour and counts
    only the requests GitHub charges, since authorized 304s are free;
  - the PRs pane spends at most 200 an hour, core requests and GraphQL
    points together;
  - neither starts a refresh when `x-ratelimit-remaining` is below 1,000,
    so in a busy hour the wall falls back to staler data before Chris's
    sessions run short.

  Both producers send the token on all their GitHub reads, search included.
  An authenticated caller gets 30 searches a minute in place of 10. The fleet
  producer keeps reading without a token. Its one search every five minutes
  fits inside the anonymous limit, and a third unit holding the token would
  buy nothing.

## Consequences

- **pub now holds three credentials**, each loaded only into the units that
  use it: the Home Assistant token (ADR-0014), the Grafana Viewer token
  (ADR-0017) and this one.
- **A leaked token can read only what anyone can read.** It cannot reach a
  private repository or write anything. What it can do is spend Chris's rate
  limit, and its requests appear in GitHub as his. To revoke it, delete it
  under GitHub → Settings → Developer settings → Fine-grained tokens. The
  producers then fall back as above.
- **The token must be rotated four times a year.** A missed rotation costs
  the PRs pane's state column and the focus panes' freshness, and nothing
  else. The "no GitHub token" footer makes the lapse visible.
- **The focus panes refresh about once a minute** where they took about
  seven, which closes #31's freshness problem. #31 stays open for the change
  to the producer.
- **Check runs need a test at the first seed.** GitHub's page on
  fine-grained tokens lists "Using fine-grained personal access token to call
  the Checks API" among the features they don't support [3], while the
  Checks API's own page says authenticated users can view check runs [4].
  If the token is refused on `GET …/commits/{ref}/check-runs`, the focus
  producer reads check state some other way: through GraphQL's
  `statusCheckRollup`, which #137 uses for the PRs pane, or, failing that,
  check runs without the token. The test is part of kalmia#280's verify step.
- **The wall's GitHub reads now depend on a person's account.** If Chris's
  account is ever suspended or its tokens are revoked in bulk, the producers
  fall back to anonymous reads; they do not stop.

## Alternatives considered

- **No token, keep #31's pacing.** It costs nothing and keeps the viewport
  free of GitHub credentials, but the PRs pane can't afford the per-PR
  column, and the focus panes stay about seven minutes stale. Chris chose
  the token (#136, 2026-11-02).
- **A token for the PRs pane alone,** as #136 first proposed. The focus
  producer has the same budget problem and needs the same grant. Chris added
  it on 2026-11-04.
- **A token for each producer.** It gives two rotations for one grant, and
  revoking either one leaves the same exposure. One file and two
  `LoadCredential=` lines are simpler.
- **A classic token with no scopes.** It also reads only public data, but a
  classic token's reach is set by scopes added later, and nothing forces it
  to expire. A fine-grained token states its limit, public repositories and
  read-only, when it is minted.
- **A GitHub App installation token.** It would have its own rate limit
  instead of Chris's, but pub would hold the app's private key, which can
  mint tokens with everything the app is granted. That is a stronger
  credential than a public read needs.
- **A separate machine account.** It also gives a separate budget, but it
  is another account to own and secure. At a fifth of the budget, the share
  doesn't justify it.
- **A longer expiry (a year) or none.** Fine-grained tokens allow up to 366
  days or no expiry [3]. Chris chose 90 days.

## References

1. GitHub, "Rate limits for the REST API": "The primary rate limit for
   unauthenticated requests is 60 requests per hour"; for a personal access
   token, "All of these requests count towards your personal rate limit of
   5,000 requests per hour."
   <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>
2. GitHub, "Best practices for using the REST API": "Making a conditional
   request does not count against your primary rate limit if a `304` response
   is returned and the request was made while correctly authorized with an
   `Authorization` header."
   <https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api>
3. GitHub, "Managing your personal access tokens": "Tokens always include
   read-only access to all public repositories on GitHub"; expiry from 1 to
   366 days or none, subject to an owner's lifetime policy; the
   fine-grained tokens' list of unsupported features.
   <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>
4. GitHub, "REST API endpoints for check runs": "OAuth apps and authenticated
   users can view check runs and check suites, but they are not able to
   create them."
   <https://docs.github.com/en/rest/checks/runs>

All retrieved 2026-11-04.
