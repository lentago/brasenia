# pipeline producer (pipeline.json → the change-pipeline pane)

**What you're about to do:** run a small stdlib-only Python process
(3.9+) that reads drosera's change-pipeline document and, while any repo has
a change in flight, keeps one pane on the viewport bus showing where each
change has got to. It reads `<url-base>/viewport/pipeline.json` and writes
`<webroot>/viewport/panes/change-pipeline/{pane.html,manifest.json}`.

**Why bother:** this is the "Change-pipeline pane" item of
[#26](https://github.com/lentago/brasenia/issues/26). A merge travels
`pushed → PR open → checks → merged → applied → live` over a few minutes,
and the household wants to glance up and see it moving, or see that it got
stuck. The pane is `class: activity`, so it outranks a focus pane while a
change is travelling, and it goes away once the change is live. The
compositor ([#27](https://github.com/lentago/brasenia/issues/27)) decides
whether it shows; this process only puts it on the bus.

**Time:** a minute to try it against the fixture (below). Running it for
real on pub is a kalmia unit (`brasenia-pipeline.service` beside
`brasenia-focus.service`, running
`python3 -m pipeline_producer --webroot /srv/www --url-base http://pub.lan`),
not something this repo deploys.

## Try it

From `producers/pipeline/`:

```sh
W=$(mktemp -d)
python3 -m pipeline_producer --once --webroot "$W" \
  --url-base "file://$PWD/tests/fixtures/in-flight" --now 2026-10-07T22:11:00Z
ls "$W/viewport/panes/change-pipeline/"
```

The fixture's `generated_at` is in the past, so `--now` sets the clock to
just after it; without it the document reads as stale and nothing is
written. Swap `in-flight` for `example` (the schema-1 example from
[drosera#266](https://github.com/lentago/drosera/issues/266), copied
verbatim) and nothing is in flight, so no pane is written.

Options: `--url-base` (default `http://pub.lan`; `file://` works too),
`--interval` (default 15 s), `--once` (one cycle, then exit), `--now`
(pretend the clock reads this RFC 3339 time). Logs go to stdout, which is
the journal under systemd.

## How you know it worked

- `panes/change-pipeline/` holds `pane.html` and `manifest.json`, and no
  `.partial` files. `manifest.json` reads `class: activity`,
  `ttl_minutes: 15`, `author: pipeline-producer@pub`, `origin: operator`,
  `title: 2 changes in flight`.
- Opening `pane.html` in a browser at 1280×720 shows one strip for drosera
  (red outline, "stuck 9 min", the marker running into `live`) and one for
  kalmia (the marker running into `applied`). brasenia has landed and is not
  shown. "data as of HH:MM" sits bottom-left; the bottom-right corner is
  empty, kept clear for the clock.
- `../../bin/pane --bus "$(mktemp -d)" claim t --class activity --title t "$W/viewport/panes/change-pipeline/pane.html"`
  accepts the page (no `<script src=`, `<link href=` or `src="http`).
- The tests pass: `python3 -m unittest discover -s tests`.

## How it works

Each cycle:

1. Fetches `<url-base>/viewport/pipeline.json`. On pub that is Caddy
   proxying to drosera's producer on LXC 105 (a kalmia change); no
   credential is involved.
2. If the document is missing, unreadable, not `schema: 1`, or its
   `generated_at` is more than 5 minutes old, nothing is known to be in
   flight. A pane already up is **held**: its strips stay, its
   `manifest.json` is not renewed, and only its stamp is rewritten to
   `data as of HH:MM · no fresh pipeline data, last tried HH:MM`. Once
   `created + ttl_minutes` passes, the directory is removed. With no pane up,
   nothing is written.
3. Otherwise, the repos with `in_flight: true` are taken oldest
   `in_flight_since` first. With none, the pane directory is removed (the
   activity sank). With some, `pane.html` and then `manifest.json` are
   written, each as `x.partial` renamed to `x`, with `created` set to the
   cycle time, so the 15-minute TTL slides while anything is in flight.

The producer writes only `panes/change-pipeline/`. If that directory holds
a manifest with another `author`, it is left alone and the cycle logs a
warning.

## The pane

One 1280×720 band, self-contained: inline CSS and inline SVG, no scripts,
no external assets. Dark background `#111217`, text `#f3f0e8`, muted
`#b8bcc6`. Text is 20 px or larger, inside 24 px margins. The header reads
"N changes in flight". Below it is one strip per in-flight repo, at most
four (the four oldest `in_flight_since`), with `+N more` at the right of
the header if more are in flight.

Each strip has a header line (repo name, head SHA, minutes in flight,
`stuck N min` in red when `stuck: true`) and six boxes:
`pushed → PR open → checks → merged → applied → live`. Each box shows the
stage, the short SHA and `detail`, filled by `state` in the Change —
Pipeline dashboard's palette: 3 green `#73BF69`, 2 red `#F2495C`, 1 blue
`#5794F2`, 0 grey `#6b7280`. A stuck repo's strip has a red outline.

**The marker.** The boxes are joined by small inline-SVG arrows. The arrow
into the change's frontier is drawn as a dashed line whose dashes travel
left to right (a `stroke-dashoffset` keyframe animation). The frontier is
the first stage after the furthest green one. Read literally, "the furthest
stage that is not yet green" is almost always `live` while a change is in
flight. The frontier is where the change actually is: a failed `applied`
stops the marker at `applied`.

The layout is fixed-height: a 64 px header and four 130 px strips with
8 px gaps fill 616 px of the 622 px main area, which ends 74 px above the
bottom edge. The stamp ends 356 px short of the right edge, so the
bottom-right 220×50 px clock corner stays clear.

The pane contract and manifest shape are the v1 contracts in
[`docs/concept.md`](../../docs/concept.md); the document is schema 1 as
pinned in drosera#266.

## Tests

```sh
python3 -m unittest discover -s tests
```

They run against the fixtures under `tests/fixtures/` (`example` is
drosera#266's example document; `in-flight` adds a stuck drosera change, a
kalmia change mid-apply and a landed brasenia) served over `file://` from
temp directories. They cover: nothing in flight writes no pane; one in
flight writes the pane and manifest with the expected strip; a stale or
missing document keeps the pane without renewing it, then removes it at
TTL; a changed document rewrites the pane; cleanup when the last repo
lands; someone else's `change-pipeline` directory is left alone; and the
render (the contract checks, the marker edge, the four-strip cap). CI runs
them on 3.9 and 3.12 (`.github/workflows/pipeline-producer-tests.yml`,
informational, never a required check).
