# links producer (standing slots → link panes)

*Written with Claude Code (Anthropic), like the rest of this repository: see
the [README](../../README.md).*

**What you're about to do:** run a small stdlib-only Python process (3.11+)
that reads the household's standing slots from `viewport/rubric.json` and
keeps one link pane on the viewport bus for each, at
`<webroot>/viewport/panes/<pane-id>/`.

**Why bother:** a standing slot keeps a web page on the wall as a resting pane
([#97](https://github.com/lentago/brasenia/issues/97),
[ADR-0018](../../docs/adr/0018-standing-slots-are-household-settings.md)). The
household adds and removes slots in `viewport/configure.html`, and this is the
part that puts them on the bus. A link pane names a web page instead of
shipping `pane.html`
([ADR-0016](../../docs/adr/0016-panes-carry-a-revision-and-may-link-a-web-page.md)).

**Time:** a minute against a temp directory. Running it for real on pub is
kalmia's `brasenia-links.service`
([lentago/kalmia#203](https://github.com/lentago/kalmia/pull/203)).

## What it does each cycle (every 30 s)

1. **Reads the slots.** It reads `viewport/rubric.json`, the effective
   settings the compositor publishes, and takes every `link.<pane-id>` entry:
   `{"title", "source"}`, already validated by the compositor. If the file
   can't be read, it changes nothing and its panes leave the bus at their TTL.
2. **Keeps a pane per slot.** For each slot it writes
   `panes/<pane-id>/manifest.json` (`x.partial` then `x`):
   - `class: ambient`, `origin: operator`, `dwell_s: 60`
   - `author: links-producer@pub`
   - `ttl_minutes: 10`, with `created` renewed every cycle
   - the slot's `title` and `source`, and no `pane.html`

   A pane another author owns is left alone, and logged once.
3. **Drops removed slots.** It deletes its own panes (author
   `links-producer@pub`) whose slot is gone.

The compositor shows link panes only with `--link-panes`, which stays off until
the renderer on LXC 118 can show outside sites safely
([lentago/kalmia#194](https://github.com/lentago/kalmia/issues/194)). Until
then these panes wait on the rubric board as `off`.

## Try it

From `producers/links/`:

```sh
python3 -m links_producer --webroot /tmp/w --once      # one cycle against /tmp/w/viewport/
python3 -m unittest discover -s tests                   # the tests
```
