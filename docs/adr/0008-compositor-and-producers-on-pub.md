# ADR-0008: The compositor and the producers run on pub; the display guest stays a client

**Status:** Accepted (2026-10-07; live since kalmia#141)

## Context

The viewport bus lives on the NAS web share under `web/viewport/`
([ADR-0004](0004-nas-file-pane-bus-write-then-rename.md)). LXC 118 (the
display guest, `lunaria`) mounts no NAS share by design
([ADR-0005](0005-product-runtime-split-with-kalmia.md): the display leg is
credential-free and its only input is `http://pub.lan/`), so it cannot write
the compositor's pointer. Pub (LXC 114) mounts the share at `/srv/www` and
serves it as `http://pub.lan`.

The compositor and every producer must write to the bus; the clients (the
Cast receiver, the Roku adapter on 118) only read the pointer.

## Decision

The compositor and the producers (focus today, the change-pipeline pane
next) run on pub as the unprivileged `brasenia` system user, in the share's
gid-1000 `webdrop` group, from a role-managed checkout (`/srv/brasenia`,
kalmia's `pub` role). LXC 118 is a pure client.

Producers that need data from elsewhere read it over HTTP from pub.lan
rather than holding credentials — for example `viewport/pipeline.json`,
proxied by Caddy from drosera's producer on LXC 105. This keeps ADR-0005's
credential-free viewport rule.

## Consequences

- Pub becomes a runtime, not only a webserver: its role now carries services
  and the Caddy config.
- New brasenia code goes live through the daily Cast-publisher pull plus
  restart.
- A producer that needs a secret is a smell; push the data to pub.lan
  instead and read it from there.
- The 118 ↔ pub split is what lets the HLS chain be turned down later
  ([#12](https://github.com/lentago/brasenia/issues/12)) without touching
  the bus.

## Alternatives considered

- **118 serving the pointer over HTTP itself.** Needs the compositor's
  output on 118, which means either giving 118 write access to the bus or
  copying state to it. That breaks the "pure client" property, and the
  display guest would become a server whose restarts or HLS turndown take
  the pointer with them.
- **The compositor on the NAS.** The NAS is storage, not a place we
  provision or deploy services from; there is no role-managed checkout,
  unit management, or CI-applied path there, so the compositor would be an
  unmanaged runtime on the one box holding everyone's data.
- **A share mount on 118.** Directly contradicts ADR-0005's credential-free
  display guest: a mount is a standing credential and write path on the
  always-on, least-scrutinized leg of the chain.
