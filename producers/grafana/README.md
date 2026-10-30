# grafana producer (Grafana Cloud dashboards → panes)

> **Authorship:** co-written with [Claude](https://claude.ai) (Anthropic), who
> wrote the code and prose; the maintainer directs and reviews the work.

**What you're about to do:** run a small stdlib-only Python process (3.11+)
that asks the Grafana Cloud stack's render API for a PNG of each configured
dashboard and keeps one resting pane per dashboard on the viewport bus:
`<webroot>/viewport/panes/<pane>/`, holding `dashboard.png` and a
`pane.html` that frames it.

**Why bother:** Grafana Cloud needs a login, so a dashboard URL can't be a
link pane: LXC 118's renderer would show the login page, and it stays
credential-free by design ([ADR-0016](../../docs/adr/0016-panes-carry-a-revision-and-may-link-a-web-page.md)).
pub holds a Viewer token instead, and the dashboards become ordinary panes
that the Roku remote can peek at and pick as the default resting pane like
any other ([#98](https://github.com/lentago/brasenia/issues/98),
[ADR-0017](../../docs/adr/0017-grafana-panes-rendered-on-pub.md)). Each is
`class: ambient`, so anything urgent still takes the screen.

**Time:** a minute to run the tests. Running it for real on pub is kalmia's
`brasenia-grafana.service`
([kalmia#202](https://github.com/lentago/kalmia/issues/202)),
which hands the process its token as a systemd credential. This repo doesn't
deploy it.

## The token

The producer makes one kind of call, `GET /render/d/<uid>`, and a Viewer
service account is all that needs. The account is defined in drosera, which
owns the Grafana Cloud stack as code
([drosera#287](https://github.com/lentago/drosera/issues/287));
don't create it by hand. Its token is minted by hand, so it stays out of
Terraform state (ADR-0017). The token never appears in a log, a URL or on a
page. To make one, once drosera has applied the account:

1. In the stack, **Administration → Users and access → Service accounts**,
   open `brasenia-viewer` (role **Viewer**), **Add service account token**,
   name it `brasenia pub`, and copy it.
2. Put it on pub without it touching a shell history or this chat, from your
   own terminal. The prompt doesn't echo: paste the token and press Enter.

   ```sh
   read -rsp 'Grafana token: ' T && echo && printf '%s' "$T" | ssh root@pve.local \
     "ssh pve4 'pct exec 114 -- sh -c \"umask 077; cat > /etc/brasenia/grafana-token\"'" ; unset T
   ssh root@pve.local "ssh pve4 'pct exec 114 -- systemctl restart brasenia-grafana'"
   ```

To revoke it, delete the token from the service account in the stack. The
panes then leave the bus at their TTL.

## The slots

A JSON file names the dashboards; kalmia writes it on pub from its role
defaults. Each slot is one pane:

```json
{"slots": [
  {"pane": "grafana-infra", "uid": "firewalla-infra-health", "title": "Infrastructure"}
]}
```

| Key | Default | Meaning |
|---|---|---|
| `pane` | (required) | the pane id, `[a-z0-9][a-z0-9-]{0,62}` |
| `uid` | (required) | the dashboard UID (drosera freezes these, its ADR-0007) |
| `title` | (required) | the pane's title, on the board and in its footer |
| `size` | `[1232, 610]` | the CSS size Grafana lays the dashboard out at; the pane scales it into its 1848×915 frame (1.5×), so the default looks as it did on the old 1280×720 canvas. Grafana Cloud refuses a width under 1000 or a height under 500, and its renderer one over 3000; `size` plus `crop_px` must fit |
| `theme` | `dark` | `dark` or `light` (the wall is dark; prefer `dark`) |
| `refresh_s` | `300` | seconds between renders, at least 60 (ADR-0017) |
| `from`, `to` | `now-6h`, `now` | the dashboard's time range |
| `vars` | `{}` | template variables, sent as `var-<name>=<value>` |
| `crop_px` | `40` | rendered below `size` and cut off: Grafana's "Powered by" footer |
| `scale` | `1` | device scale factor, 1–3: 2 or 3 is sharper on the 4K Roku, at a slower render and a larger file |
| `dwell_s` | `60` | written to the manifest; ignored since ADR-0020 retired rotation |
| `org_id` | `1` | the Grafana organization |

## Try it

From `producers/grafana/`, the tests drive two made-up slots through a fake
Grafana:

```sh
python3 -m unittest discover -s tests
```

Against the real stack, with a Viewer token in a file (this is a live call:
it spends a render):

```sh
W=$(mktemp -d)
python3 -m grafana_producer --once --webroot "$W" --grafana-url https://<stack>.grafana.net \
  --slots tests/fixtures/slots.json --token-file ~/grafana-token
```

Options: `--grafana-url` (required: the stack, plain `https://`, no
credentials in it), `--slots` (required), `--token-file` (default
`$CREDENTIALS_DIRECTORY/grafana-token` under systemd), `--tz` (default
`America/New_York`), `--interval` (seconds between checks for a due slot;
default 30), `--once` (render every slot once; exit 1 if any failed), `--now`.

## How you know it worked

- Each slot's `panes/<pane>/` holds `dashboard.png`, `pane.html` and
  `manifest.json`, and no `.partial` files. Each manifest reads
  `class: ambient`, `ttl_minutes` of three refreshes (15 at the default 300 s),
  the slot's `dwell_s`, `author: grafana-producer@pub`, `origin: operator`.
- At 1920×1080, `pane.html` shows the dashboard inside the 36 px margins, with
  no Grafana header or sidebar and no "Powered by" footer, and a footer
  bottom-left reading "Infrastructure · Grafana · as of 8:40 PM". The
  bottom-right corner is empty, kept clear for the clock. If Grafana's footer
  still shows at the frame's bottom edge, raise that slot's `crop_px`.
- The journal says nothing after the first render; a failure logs one line
  naming the slot and when it will try again.

## How it works

Every `--interval` seconds it checks for slots that are due. For each, one at
a time:

1. Reads the token file. With none, or one with whitespace or control
   characters inside it, it logs once (never the value) and writes nothing;
   `--once` then exits 1.
2. `GET <stack>/render/d/<uid>?width=…&height=<height + crop_px>&theme=…&kiosk=1&tz=UTC-04:00&…`
   with the token as a bearer header. Redirects aren't followed: Grafana
   answers a missing or rejected token with a redirect to its login page.
3. On a PNG, writes `dashboard.png`, then `pane.html` with the PNG inlined
   as a `data:` URI (so the page is self-contained; its content revision, ADR-0016, moves
   with every good render, since the page carries the render's "as of" time), then `manifest.json`. The
   slot is next due in `refresh_s`.
4. On a failure (network, a rejected token, HTTP 429 or 5xx, a body that
   isn't a PNG), changes nothing. The slot waits `refresh_s`, then twice
   that after each further failure, up to an hour, and never less than a
   429's `Retry-After`, which pauses every slot (the limit is the stack's).
   Any failure counts, a write error included, and one slot's never keeps
   another from rendering. The pane keeps its last image, stamped with its
   time, until its TTL, which runs from the last good render: at 300 s one
   failure keeps it (the retry comes at 600 s, before the 900 s TTL), a second
   leaves it off the bus for about five minutes until the retry at 1200 s. A
   dead token or stack takes it off the bus.

Files are written `x.partial` then renamed, `manifest.json` last. A pane
directory with another author's manifest is left alone. A slot removed from
the file leaves its pane to expire.

## Tests

```sh
python3 -m unittest discover -s tests
```

They run made-up slots (`tests/fixtures/slots.json`) through a fake transport
that answers with generated PNGs, with no network and no token. CI runs them
on 3.11 and 3.12 (`.github/workflows/grafana-producer-tests.yml`,
informational, never a required check).
