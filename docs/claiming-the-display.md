# Claiming the display

**What you're about to do:** decide whether something deserves the household
wall display, and if it does, put it on the viewport bus (the shared folder on
the NAS, `/mnt/lentago/web/viewport`, where panes are dropped) with `bin/pane`
so the compositor (the service on pub that ranks what is on the bus and
decides what the wall shows) can show it.

**Why bother:** the wall is a shared, glanceable surface, and a session that
learns something the household would want to see (a failing deploy, a
decision waiting on someone, a long job finishing) has no other way to say
so. Claiming is cheap and safe: you write a page into your own directory, and
the compositor, not you, decides whether it shows.

**Time:** a minute to claim; nothing to do afterwards except release when the
thing resolves (or let the TTL, the time to live after which an unrefreshed
claim expires, do it).

## Is it screen-worthy?

Yes, if the household would want to glance up and see it. A pull request that
needs a decision, an alert, a live feed: yes. Your own progress, a log tail,
something only you care about: no. When in doubt, don't claim; the focus
producer ([`producers/focus/`](../producers/focus/)) already puts open pull
requests up for any repo you are working in.

## The seven classes

Priority order, with the default TTL from
[rubric v1](concept.md#rubric-v1) and one example each.

| Class | Default TTL | Example |
|---|---|---|
| `alert` | 60 min | Production deploy failing |
| `attention` | 240 min | A decision is waiting on a person |
| `live` | none, pass `--ttl` | A drone feed is publishing |
| `activity` | 60 min | A fleet run is working through a backlog |
| `focus` | 10 min | Open pull requests for the repo in use |
| `ambient` | none, pass `--ttl` | Weather, while fresh |
| `briefing` | none, pass `--ttl` | The morning brief |

Rubric v1 describes the TTL of `live`, `ambient` and `briefing` as "while the
publisher is present", "while fresh" and "never". A hand claim has no
publisher to watch, so `pane claim` asks for an explicit `--ttl` for those
three.

## Two rules

1. **Write only your own pane directory.** Never edit or delete another
   writer's pane. `pane renew` and `pane release` refuse a pane whose author
   is not you, and there is no force flag.
2. **The compositor alone decides what shows.** A claim is a request. Rank,
   rotation and fallback are the compositor's; do not try to force the
   pointer.

## The pane contract in five lines

The full contract is in [concept.md](concept.md#the-pane-contract).

1. One self-contained HTML file: inline CSS and JS, no external assets
   (`pane claim` refuses `<script src=`, `<link href=` and `src="http`).
2. 1280 px wide; height an exact multiple of 720 px, at most 2880.
3. Every 720 px band stands alone; nothing straddles a boundary.
4. Dark background, body text at least 20 px, 24 px safe margins.
5. Keep the bottom-right 220×50 px of each band clear (the clock overlay).

## Using `pane`

The bus root is `--bus` or `$VIEWPORT_DIR`, default
`/mnt/lentago/web/viewport`. Pane ids are `[a-z0-9][a-z0-9-]{0,62}`. The
bus layout and manifest fields are in
[Contracts v1](concept.md#contracts-v1); this page does not restate them.

```sh
# Claim: writes pane.html, then manifest.json, and prints the pane's URL.
./bin/pane claim deploy-failing --class alert --title "brasenia deploy failing" \
    --repo lentago/brasenia deploy.html
generate-page | ./bin/pane claim review-needed --class attention --title "PR #42 needs you" -

# Keep it up a while longer (slides the TTL from now), then take it down.
./bin/pane renew deploy-failing --ttl 90
./bin/pane release deploy-failing

# What is on the bus, and what the compositor decided.
./bin/pane ls
```

`--origin` is `operator` by default (use `fleet` for unattended runs),
`--dwell SEC` sets rotation time among equals, and `--author` overrides the
default `<user>@<hostname>`. Renew and release identify you the same way, so
pass the same `--author` you claimed with if you set one. Exit codes: 0 ok,
1 refused (the reason is on stderr), 2 usage.

## If you forget to release

Nothing breaks. A pane stops being live when `created + ttl_minutes` passes,
and the compositor moves on. The directory stays on the bus until its author
removes it; `pane ls` shows it as `expired`.
