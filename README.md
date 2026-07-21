# brasenia

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/lentago/brasenia)

Brasenia (watershield) carpets New England ponds with small floating leaves —
little panes resting on the water's surface. **brasenia** is the Lentago Labs
shared viewport: one always-on wall display whose content is chosen by a
**rubric, not a remote**. Panes surface when there's something worth showing —
a PR awaiting review, a failing backup, a deploy in flight — and sink back
when they resolve; the daily morning brief is the resting surface underneath.
Today it drives a 32" Roku TV via a live HLS stream; the pane bus and
compositor are the roadmap.

*(Renamed from `lunaria` on 2026-07-20, hours after creation — Lunaria annua
is a European garden escape, and the Lentago codename roster is New England
natives only.)*

**Authorship:** The code and documentation in this repo are co-written with
[Claude](https://claude.ai) (Anthropic). I direct the work and review the
output; Claude writes the code and prose. I'm an infrastructure operator, not a
software engineer — please don't read this repo as a portfolio of coding
ability.

## What's here

- `docs/concept.md` — the product concept: pane / rubric / compositor model,
  the pane contract, rubric v0, migration phases.
- `roku-app/` — the BrightScript dev channel the TV runs: a full-screen HLS
  `Video` node with the **mandatory auto-retry handler** (a bare Video node
  never recovers from a publisher restart; this one rejoins ~1 s after the
  stream returns).
- `scripts/deploy-roku.sh` — zip + sideload via the Roku dev installer
  (digest auth; credentials via environment, never committed).

## What's deliberately elsewhere

Brasenia follows the fleet's separation of product from provisioning:

| Piece | Where it lives |
|---|---|
| LXC 118 guest definition | [`kalmia`](https://github.com/lentago/kalmia) `terraform/containers.tf` (CI-applied) |
| Runtime stack (mediamtx, shooter/rotator/encoder scripts, systemd units) | [`kalmia`](https://github.com/lentago/kalmia) `roles/lunaria/` + `docs/lunaria.md` |
| Brief publishing (Google Drive → `pub.lan`, the only credentialed leg) | [`kalmia`](https://github.com/lentago/kalmia) `roles/pub/` |

(kalmia's role, docs, and the container hostname still carry the `lunaria`
name from before the rename — completing it through runtime is owned by
[kalmia#63](https://github.com/lentago/kalmia/issues/63) under the fleet
rename discipline: legacy names are tracked debt, never permanent.)

The running container is **credential-free by design**: its only input is
`http://pub.lan/`. This repo owns the concept, the TV client, and (Phase 2)
the compositor.

## How it works today (Phase 1)

```
 claude.ai routine (8:08 ET) → Google Drive → pub (LXC 114) → http://pub.lan/brief/
      ▼
 viewport LXC (118, pve4): headless Chromium shoots the TV edition →
      720p bands rotate through frame.png → ffmpeg (image2pipe, H.264+AAC)
      → mediamtx → HLS :8888
      ▼
 Roku dev channel (this repo's roku-app/) → 32" play-room TV
```

Glass-to-glass latency runs 7–17 s depending on playlist join depth; the whole
chain survives publisher restarts unattended. Validation evidence and the
operational gotchas (mediamtx `?cookieCheck=1` redirect, Roku retry behavior,
headless-Chromium cache staleness) are summarized in `docs/concept.md`.

## Roadmap

- **Phase 2** — NAS pane bus (`web/viewport/panes/<pane>/` + `manifest.json`)
  and the rubric compositor on the viewport LXC; briefing and Grafana become
  the first two pane classes.
- **Phase 3** — governance snippet rolls out to all local Claudes and the
  claytonia fleet; panes start arriving from real activity (PR queue, job
  status, HA alerts).

---

*Part of the [Lentago Labs](https://github.com/lentago) portfolio.*
