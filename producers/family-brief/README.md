# family brief producer (the Family Brief → a today-and-tomorrow pane)

**What you're about to do:** run a small Python process (3.11+, standard
library only, so there is nothing to install) that reads the morning Family
Brief document and keeps one pane on the viewport bus. A pane is one
self-contained web page offered to the wall display; the viewport bus is the
shared folder on pub (`viewport/panes/`) where producers drop panes and the
[compositor](../../compositor/) picks which one the wall shows. This pane shows
just today and tomorrow: who needs to be where, the coverage note for today,
and any decision that lands on those two days. It reads `--source` (default
`http://pub.lan/family-brief/latest.json`) and writes
`<webroot>/viewport/panes/family-today/{pane.html,manifest.json}`.

**Why bother:** the full Family Brief is an email and a private dashboard
page, both too long to glance at from across a room. This pane is the
glanceable cut for the wall: one 1920×1080 band (the pane contract's canvas,
ADR-0019) at the 30 px text floor, no scrolling, and one band only (ADR-0020).
Detail that doesn't fit leaves the wall; the full brief keeps it.

**The desk edition is retired.** `detail.html` was a denser 1920×1080 edition
with every decision and the to-do list. Its 18–22 px text was below the 30 px
floor, so the producer no longer writes it, and removes one left behind
(#115).

**This week:** a second resting pane, `panes/family-week/`, shows the brief's
seven days from today, one row per day. Each row has the day, any coverage
flag the brief raised for it (a gap or a crunch, in amber), how many
decisions and to-dos land on it, and its items. `pane.html` is one
1920×1080 band, with each day's items on two lines. Both family panes are
`ambient`, so they share the resting rung, and their manifests set
`dwell_s: 60`: with no default resting pane they take turns slowly, and the
household can hold one from the Roku remote's Left/Right or the configurator.

**The briefing slot:** each cycle that loads a brief also writes
`viewport/briefing/{pane.html,manifest.json}`, the compositor's
fallback when nothing on the bus is live. Unlike the pane, the slot is written
whatever the brief's age, and an old one says "No brief since Fri 10/23"; the
manifest's `published` (the brief's `generated_at`) is what the compositor's
`briefing.max_age_hours` setting judges. A slot whose manifest names another
author is left alone.

**Time:** a minute to try it against the fixture (below). Running it for
real on pub is not set up yet. The proposed deployment is a systemd unit in
kalmia's pub role running `python3 -m family_brief_producer --webroot /srv/www`
from a brasenia checkout, plus kalmia serving the brief at
`/family-brief/latest.json`; neither exists yet, and this repo deploys
neither.

## Try it

From `producers/family-brief/`:

```sh
W=$(mktemp -d)
python3 -m family_brief_producer --once --webroot "$W" \
  --source "file://$PWD/tests/fixtures/example/latest.json" --now 2026-10-25T15:00:00Z
ls "$W/viewport/panes/family-today/"
```

The fixture is a made-up family dated 2026-10-25, so `--now` puts the clock
on that day. Try `--now 2026-10-26T15:00:00Z` for the morning after (today
then comes from the brief's week list and the header says no brief has
landed yet), and `--now 2026-10-27T15:00:00Z` to see the pane removed.

Options: `--source` (`http://` or `file://`), `--tz` (default
`America/New_York`, what "today" means), `--interval` (default 60 s),
`--once` (one cycle, then exit), `--now` (pretend the clock reads this
RFC 3339 time). Logs go to stdout, which is the journal under systemd.

## The input

The document is the one the Family Brief routine writes each morning
(schema 1). The routine stores it on its dashboard page and also drops a copy
named `latest.json` in the Drive folder pub publishes; kalmia's pub role serves
that copy at `/family-brief/latest.json`. The pane uses these fields and
ignores the rest:

| Field | Used for |
|---|---|
| `schema` (1), `date` (`YYYY-MM-DD`) | Required. The brief is fresh on its own day and the next. |
| `edition` | Header, right side. |
| `status_line` | Not shown (it was the retired desk edition's header). |
| `today.items`, `today.coverage` | The Today column on the brief's own day. |
| `this_week[]` (`date`, `items`) | Tomorrow, and Today on the day after the brief. |
| `decisions[]` (`title`, `dates`) | The decision strip: up to two whose `dates` include today or tomorrow. |
| `todos[]` (`tag`, `text`, `deadline`, `due`) | Counted on This week's day rows ("1 due"); the list itself is not shown. |
| `people` (`{key: {label, color}}`) | Optional. Each person's colour on a dark background; without it, colours follow a fixed palette in order of appearance. |

An item is `{time, people, who, what, where?, bring?, note?, legacy?, unconfirmed?, cancelled?}`.

## How you know it worked

- `panes/family-today/` holds `pane.html` and `manifest.json` (no `detail.html`),
  and no `.partial` files. `manifest.json` reads `class: ambient`,
  `ttl_minutes: 30`, `author: family-brief-producer@pub`,
  `origin: operator`, `title: Family: today and tomorrow`.
- Opening `pane.html` at 1920×1080 shows a green header with the date, two
  columns (Today with one item and a coverage note, Tomorrow with five
  rows), and an amber strip with one decision and "2 more on the board".
  The bottom-right corner is empty, kept clear for the clock.
- `../../bin/pane --bus "$(mktemp -d)" claim t --class ambient --ttl 5 --title t "$W/viewport/panes/family-today/pane.html"`
  accepts the page (no `<script src=`, `<link href=` or `src="http`).
- The tests pass: `python3 -m unittest discover -s tests`.

## Behaviour worth knowing

- **Class `ambient` (priority 40).** While the pane is live it outranks the
  morning-brief fallback, so it becomes the wall's resting surface; anything
  `focus` or above still wins. To make it rotate with the briefing instead,
  change `PANE_CLASS` in `producer.py`.
- **Freshness.** Each cycle re-renders and renews the 30-minute TTL while the
  brief is dated today or yesterday. A brief older than that removes the
  pane. If the source is unreachable, the pane is left alone and its TTL
  takes it down.
- **Day rollover.** "Today" is the household's date (`--tz`), so at midnight
  the columns move on by themselves, using the same brief until the next one
  lands.
- **Busy days.** Each column has six two-line slots (five under the coverage
  note). A day with more items shows the first ones and "+N more on the
  board".

## The Google Doc

The same brief also goes out as a Google Doc, so it can be read on a phone
away from home, and shared, which `pub.lan` can't be
([#90](https://github.com/lentago/brasenia/issues/90)). `family_brief_producer.doc`
renders it as flowing HTML, built from the same `latest.json` as the panes so
the two can't disagree:

```sh
python3 -m family_brief_producer.doc tests/fixtures/example/latest.json > brief.html
```

- **Sections**, each left out when empty: the day (coverage note, then
  items), Needs a decision, To do, the rest of the week (with the week
  strip's gap and crunch flags), Coming up, FYI, and the brief's footer.
- **Markup Google Docs' import keeps:** headings, paragraphs, bulleted lists,
  bold and inline colour. People keep their legend colour, darkened to read
  on a white page.
- **Absolute dates, no "today".** The output depends only on the brief, so an
  unchanged brief renders the same bytes. pub uses that to update the Doc
  only when the brief changes.

The upload is kalmia's `publish-family-brief` on pub. When a new
`latest.json` lands, it runs this module as the unprivileged `brasenia` user,
then imports the HTML into one Google Doc with rclone, updated in place so
the link stays the same. The Doc's Drive folder is shared with the household.
