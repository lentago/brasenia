# home producer (Home Assistant → the home and weather panes)

**What you're about to do:** run a small stdlib-only Python process (3.11+)
that reads Home Assistant's REST API and keeps two resting panes on the
viewport bus: `<webroot>/viewport/panes/home/` (alarm, people, climate, doors
and windows, locks, water) and `<webroot>/viewport/panes/weather/` (now, the
next day by the hour, the coming days).

**Why bother:** these are two of the positions on the resting-pane ladder
([#86](https://github.com/lentago/brasenia/issues/86)) that the Roku remote's
Left/Right picks the household's default from
([ADR-0013](../../docs/adr/0013-the-remote-sets-the-default-resting-pane.md)).
Both are `class: ambient`, so anything urgent still takes the screen. The
compositor decides whether they show; this process only puts them on the bus.

**Time:** a minute to render the fixtures (below). Running it for real on
pub is kalmia's `brasenia-home.service`, which hands the process its token
as a systemd credential. This repo doesn't deploy it.

## The token

Home Assistant answers only with a long-lived access token, and it has no
read-only role. The producer makes two read calls (`GET /api/states` and the
answer-only `weather.get_forecasts`), and the token never appears in a log or
on a page. [ADR-0014](../../docs/adr/0014-home-and-fleet-feed-resting-panes.md)
records why pub holds it. To make one:

1. In Home Assistant, **Settings → People → Users → Add user**: name it
   `brasenia`, leave **Administrator** off, and turn **Can only log in from
   the local network** on.
2. Log in as that user (a private window), open its **Profile → Security →
   Long-lived access tokens → Create token**, name it `brasenia pub`, and copy
   it.
3. Put it on pub without it touching a shell history or this chat, from your
   own terminal. The prompt doesn't echo: paste the token and press Enter.

   ```sh
   read -rsp 'Home Assistant token: ' T && echo && printf '%s' "$T" | ssh root@pve.local \
     "ssh pve4 'pct exec 114 -- sh -c \"umask 077; cat > /etc/brasenia/ha-token\"'" ; unset T
   ssh root@pve.local "ssh pve4 'pct exec 114 -- systemctl restart brasenia-home'"
   ```

To revoke it, delete the token from that user's profile, or delete the user.

**IPv4, on purpose.** For an `http://` URL whose host has an IPv4 address,
the producer connects to that address and sends the original `Host` header
(#88). On a dual-stack LAN the name also resolves to a global IPv6 address,
which Home Assistant doesn't count as local, so a "local network only" user
is refused there with HTTP 401.

## Try it

From `producers/home/`, render the made-up house in `tests/fixtures/`:

```sh
W=$(mktemp -d)
python3 - "$W" <<'EOF'
import sys; sys.path[:0] = ["tests", "."]
from helpers import Clock, forecast, states
from zoneinfo import ZoneInfo
from home_producer import home, weather
tz, now = ZoneInfo("America/New_York"), Clock()()
open(sys.argv[1] + "/home.html", "w").write(home.render_home(home.summarize(states()), now, tz))
w = weather.pick(states())
open(sys.argv[1] + "/weather.html", "w").write(
    weather.render_weather(w, forecast("hourly"), forecast("daily"), now, tz))
EOF
ls "$W"
```

Against a real Home Assistant, with a token in a file:

```sh
python3 -m home_producer --once --webroot "$W" --ha-url http://homeassistant.lan:8123 \
  --token-file ~/ha-token
```

Options: `--ha-url` (default `http://homeassistant.lan:8123`), `--token-file`
(default `$CREDENTIALS_DIRECTORY/ha-token` under systemd), `--weather` (the
weather entity; default the first `weather.*` by id), `--hide ENTITY_ID`
(repeatable: keep an entity off the home pane), `--tz` (default
`America/New_York`), `--interval` (default 60 s), `--once`, `--now`.

## How you know it worked

- `panes/home/` and `panes/weather/` each hold `pane.html` and
  `manifest.json`, and no `.partial` files. Each manifest reads
  `class: ambient`, `ttl_minutes: 10`, `dwell_s: 60`,
  `author: home-producer@pub`, `origin: operator`.
- At 1920×1080, `home.html` shows three columns (Alarm, People and Locks;
  Climate and Water; Doors & windows, open ones first, in amber) and a header
  summary such as "2 open · 1 of 3 home". `weather.html` shows the big
  temperature on the left, a temperature line over eight three-hour columns,
  and the coming days. Each page's bottom-right corner is empty, kept clear
  for the clock.
- The tests pass: `python3 -m unittest discover -s tests`.

## How it works

Each cycle (every 60 s):

1. Reads the token file. With none, it logs once and writes nothing.
2. `GET /api/states`. If Home Assistant can't be reached, or rejects the
   token, the cycle changes nothing, and the panes leave the bus at their
   10-minute TTL rather than show the house as it was.
3. Writes the home pane from the states, picking entities by domain and
   device class, so there is no list to keep up to date:
   `alarm_control_panel`, `person` (except one that is always `unknown`, a
   service account), `climate`, `lock`, door/garage_door/window/opening
   binary sensors and garage/door/gate/window covers, and moisture sensors.
   Each column's height is shared among its cards, so a long list ends in
   "+N more" instead of pushing the others off.
4. Writes the weather pane from the weather entity and its hourly and daily
   forecasts. Forecasts are fetched every 10 minutes, and a failed fetch
   keeps the last good one for up to 3 hours.

Files are written `x.partial` then renamed, `manifest.json` last. A pane
directory with another author's manifest is left alone.

## Tests

```sh
python3 -m unittest discover -s tests
```

They run against `tests/fixtures/` (a made-up house: states, an hourly and a
daily forecast) through a fake transport, with no network. CI runs them on
3.11 and 3.12 (`.github/workflows/home-producer-tests.yml`, informational,
never a required check).
