# ADR-0005: Product/runtime split with kalmia, enforced in both directions

**Status:** Accepted (2026-07-20; reconstructed 2026-08-13)

## Context

The pipeline validated on 2026-07-20 started on a laptop (ThinkPad) and was
migrated the same night to a dedicated, provisioned LXC (118, on pve4) via
kalmia: "MIGRATED TO LUNARIA (LXC 118) — 2026-07-20 ~21:20 ET" per
`docs/validation-notes-2026-07-20.md`, with the laptop's streaming stack
fully stopped and retired. This repo (brasenia) was created that same night
as the canonical home for the product/concept/client artifacts.

`CLAUDE.md` and the README both draw an explicit ownership line: LXC 118's
guest definition and the runtime stack (mediamtx, shooter/rotator/encoder,
systemd units) belong in kalmia (`terraform/containers.tf`,
`roles/lunaria/`), CI-applied on merge; the concept, Roku app, and future
compositor design belong here, and runtime scripts must not be forked into
this repo. The running container is documented as credential-free by
design — its only input is `http://pub.lan/` — so a bug or compromise in the
display path cannot expose the credentials that only the publisher (`pub`,
in kalmia's `roles/pub/`) holds.

The rename from `lunaria` to `brasenia` happened same-night in this repo, but
kalmia's role name and the LXC 118 hostname still carry the old `lunaria`
name; that gap is tracked as debt in
[kalmia#63](https://github.com/lentago/kalmia/issues/63) ("Complete the
lunaria → brasenia rename through runtime"), open at reconstruction time and
cited from both `README.md` and `CLAUDE.md` here rather than left silently
inconsistent.

## Decision

Enforce the product/runtime split in both directions: this repo (brasenia)
owns concept, Roku client, and future compositor design and must never fork
runtime scripts/units/container-shape changes into itself; kalmia owns the
LXC 118 guest, the runtime stack, and publisher credentials, and the running
display container stays credential-free with zero laptop involvement as the
standing acceptance criterion.

## Alternatives

- **Recorded at the time:** keep the pipeline running on the laptop that
  proved it out — this was the actual starting state (Phase 0/1) and was
  explicitly retired the same night in favor of the dedicated, provisioned
  container, precisely because a laptop-hosted runtime fails the "zero
  laptop involvement" / unattended-operation goal.
- **Retrospective — not considered at the time:** a single repo holding both
  the product/concept and the runtime provisioning (terraform + ansible
  role) together. Lateral — it removes the cross-repo coordination cost (two
  PRs, two CI runs, kalmia#63-style cross-repo debt tracking) at the price
  of mixing a CI-applies-on-merge infrastructure repo with a docs/BrightScript
  product repo that has no apply step at all — a real difference in blast
  radius and review posture that the split preserves.
- **Retrospective — not considered at the time:** let the display container
  hold its own read credentials to `pub` directly, instead of the
  credential-free constraint. Worse — it directly contradicts the design
  goal that a compromise of the always-on, least-scrutinized display leg
  can't reach anything credentialed; the current design keeps that box able
  to do nothing but fetch a public-on-LAN URL.

## Consequences

- Any change to the running stack must go through kalmia's CI-applied path;
  this repo's PRs, however thorough, never have a live effect on the TV — a
  fact the README calls out explicitly to avoid confusion.
- The legacy `lunaria` naming in kalmia is accepted as tracked debt
  (kalmia#63) rather than "fixed" opportunistically from this repo, which
  would fork the rename outside the runtime issue that owns it.
- Coordinating a feature that touches both sides (e.g. a new pane type
  needing both a compositor change here and a runtime dependency in kalmia)
  always costs two PRs in two repos — accepted overhead in exchange for the
  blast-radius and credential isolation above.
