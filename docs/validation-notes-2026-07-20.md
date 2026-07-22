# Roku HLS Test — NOTES

Session: 2026-07-20, operated by Home Claude per `~/roku-hls-test-spec.md`

## Phase 0 values

| Key | Value | How confirmed |
|---|---|---|
| ROKU_IP | 192.168.139.240 | ECP scan of 192.168.139.0/24:8060 |
| Roku model | TCL 32S327 "32\" play room", SW 15.2.4, wifi | `/query/device-info` |
| Dev mode (0.1) | **enabled** (`developer-enabled: true`) | `/query/device-info` |
| ROKU_DEV_PASS (0.3) | *pending — ask operator* | — |
| HOST_IP (0.4) | 192.168.139.92 (ThinkPad, wlp0s20f3, dynamic DHCP) | `ip -4 addr` |
| Roku→host path (0.5) | Same subnet 192.168.139.0/24 — no IoT VLAN. Risk: **ufw active on host**; tested empirically in Phase 4 | scan + `systemctl is-active ufw` |
| Host→Roku :80 (0.6) | open — `POST /plugin_install` returns 401 (auth required = installer alive) | curl |
| TV awake (0.7) | `power-mode: PowerOn` | `/query/device-info` |

## Phase progress (as of 2026-07-20 ~19:10 ET)

- Phase 1 ✓ workspace + deps (static binaries, no sudo needed)
- Phase 2 ✓ mediamtx v1.19.2 up, :8554/:8888 listening (pid in `out/mediamtx.pid`, log `out/mediamtx.log`)
- Phase 3 ✓ ffmpeg publishing ~30fps (pid in `out/ffmpeg.pid`, log `out/ffmpeg.log`); manifest valid, `.ts` segments @2s (mpegts confirmed)
- Phase 4 ✓ manifest HTTP 200 via HOST_IP from pve.local — **ufw not blocking 8888**, no rule needed
- Phase 5 ⏸ app built (`out/hls-test.zip`, manifest at root) — **awaiting ROKU_DEV_PASS to sideload**
- Phase 6 ⏸ operator on-glass checks

## mediamtx v1.19 gotcha: cookie-check redirect

`/board/index.m3u8` returns **302 → `?cookieCheck=1`** (+ per-session playlist
URLs). No config option to disable. Mitigation: the Roku app URL pre-bakes
`?cookieCheck=1`, which skips the redirect (verified: cookie-less curl gets
HTTP 200 directly). If playback still fails, first suspect the session-URL
handling in Roku's HLS client — a mediamtx downgrade (pre-cookieCheck) is the
fallback.

## Host deviations from spec

- No distro ffmpeg (and no non-interactive sudo): using a **static ffmpeg**
  at `~/roku-hls-test/bin/ffmpeg`. First tried johnvansickle 7.0.2 — its build
  **lacks drawtext**; switched to the BtbN linux64-gpl build (N-125705,
  2026-07-20), which has drawtext + libx264.
- mediamtx **v1.19.2** linux_amd64.
- Added `-rtsp_transport tcp` to the ffmpeg publish (reliability; localhost).
- `fontfile=` pinned explicitly in drawtext (static ffmpeg + font resolution).

## Phase 6 observations

- **Playback ✓** (19:11 ET): test pattern + clock overlay rendering on the TV
  (operator photo `~/Downloads/20260720_191130.jpg`). mediamtx logged the HLS
  session from 192.168.139.240; cookieCheck pre-bake worked — no redirect issue.
- **Latency: ~16.5s ± 0.5s** (photo-EXIF method: capture 19:11:30.879 vs
  overlay 19:11:14; host chrony 0.26 ms off NTP; phone assumed NTP-synced).
  Above the 6–15s expectation, under the 30s acceptance bar. Likely trim path
  if ever needed: 1s GOP (`-g 30`) + `hlsSegmentDuration: 1s`, smaller count.
  **Second measurement (19:21+, operator eyeball): ~7 s** — after the recovery
  rejoin the muxer was fresh (1–2 segments deep), so the player joined near the
  live edge. Latency = f(join depth in playlist); range observed 7–17 s.
- **Recovery — v1 app FAILED, v2 app PASSES:**
  - Mechanism: publisher death ⇒ mediamtx destroys the HLS muxer **and closes
    client sessions**. The bare `Video` node lands in `state=error` and never
    retries — v1 froze on last frame indefinitely (test 19:15:17 kill; still
    frozen at 19:16:35; 0 reconnects in 90 s).
  - Fix (v2, build 2): observe `state`; on `error`/`finished` stop + 3 s Timer
    + re-set content/play. Retry loops until the stream is back.
  - Re-test: kill 19:18:12 → restart 19:18:22 → **Roku rejoined 19:18:23**
    (1 s after stream return), fully unattended.
  - Verdict for buy/no-buy: pipeline + mediamtx recover instantly; recovery is
    purely client logic — any production app needs the retry handler (trivial).
- **Soak ✓ — 13.5 min clean** (19:18:23 rejoin → 19:31:45, sampled every 30 s):
  Roku held 2 established connections at every sample, same HLS session
  throughout, ffmpeg up, zero mediamtx ERR/WAR. Operator: clock advancing,
  no stalls reported.

## VERDICT — all four success criteria PASS

1. ✓ Live test pattern + burned-in clock on the Roku
2. ✓ Smooth playback 10+ min (13.5 min verified)
3. ✓ Latency measured: ~16.5 s (deep join) / ~7 s (live-edge join) — under 30 s bar
4. ✓ Survives stream restart: **automatic 1 s rejoin** with the v2 retry app
   (bare Video node does NOT recover — retry handler is mandatory)

Implication for the decoder-hardware question: the Roku-native HLS path is
viable as-is. mediamtx v1.19.2 + mpegts variant + static ffmpeg → TCL Roku TV
works end-to-end on this LAN with no firewall changes.

## Phase 7 — Grafana source (built 2026-07-20 19:45 ET)

**Design decision:** skipped the spec's Xvfb+Chromium+x11grab sketch. Grafana
is Cloud (lentago.grafana.net, no anonymous access); the laptop has no
Xvfb/chromium (sudo needed) and the desktop is Wayland. Instead: the
**`/render` endpoint** with the existing drosera SA token — a full 1280×720
kiosk PNG in ~6 s, auth solved, zero new packages. Trade-off: ~15 s slideshow
cadence, irrelevant for a 30 s-refresh dashboard. Xvfb path remains in the
spec if animated dashboards ever matter.

- Dashboard: **`firewalla-office-display` "Office Display"** — purpose-built
  for the retired pve2 wall display, resurrected for the play-room TV.
- `stream/grafana-frame-loop.sh`: curl render → atomic mv to `frame.png`
  every ~15 s; on failure keeps last good frame.
- `stream/run-grafana-stream.sh`: feeder re-cats `frame.png` per frame →
  ffmpeg image2pipe 10 fps, same proven H.264+AAC recipe, small clock overlay
  bottom-right (liveness + latency probe), GOP 2 s.
- Both launched via `setsid`; **kill with `kill -- -$(cat out/*.pgid)`** (the
  stream script is a pipeline — killing the script pid alone orphans
  ffmpeg/feeder).
- Verified: frame extracted from the live HLS shows the dashboard + advancing
  clock. Roku app needs no change (same path/URL).
- For a permanent deployment: check Grafana Cloud render rate limits/usage
  billing before running a 24/7 15 s render loop.

## Phase 7b — Morning Brief on the TV (2026-07-20 ~20:15 ET)

Frame source swapped from Grafana to the daily brief:

- **TV edition**: `http://pub.lan/brief/tv.html` — 1280×720, one screen, no
  scroll, dark, big type, bottom-right kept clear for the clock overlay.
  Today's was hand-built (in `/mnt/lentago/web/brief/tv.html`); from tomorrow
  the Morning-brief routine should emit `morning-brief-tv-YYYY-MM-DD.html`
  to the Drive folder (**routine prompt update pending — Chris pastes the
  paragraph via claude.ai/code/routines; the RemoteTrigger wholesale-job_config
  update was impractical: 64 KB inline body, one parse failure, abandoned**).
- `stream/brief-pages.py`: prefers tv.html (single page); falls back to
  slicing index.html with tolerance-based trim (BG_TOLERANCE=12 — the plain
  bbox trim saw noise to 8000 px and produced blank pages).
- `stream/brief-frame-loop.sh`: rotates `brief/page-*.png` → frame.png (12 s
  dwell), re-renders every 10 min. With a single tv page it's a static frame
  refreshed every 10 min.
- **New: `brief-sync` systemd user timer** (this laptop, `~/.local/bin/brief-sync`,
  every 15 min, linger already on): rclone-copies the Drive morning-brief
  folder → `/mnt/lentago/web/brief/`, maps newest dated file → index.html and
  newest tv-dated file → tv.html (leaves tv.html alone when Drive has none —
  protects hand-made editions). This was the missing "ThinkPad timer" leg of
  the publish chain — it did not actually exist before tonight.
- **Process-mgmt lesson #2**: `setsid nohup script &` may FORK, so `$!` is not
  reliably the new pgid — recorded .pgid files are untrustworthy. A stale kill
  left two rotation loops racing one shared temp file; the feeder cat'd a
  half-written PNG and the encoder died (Roku auto-rejoined 3 s after
  restart, as designed). Fixed: per-PID temp names in the loop, and teardown
  by pattern with self-exclusion brackets:
  `pkill -f 'brief-frame-loop[.]sh'; pkill -f 'run-grafana-stream[.]sh'; pkill -f 'roku-hls-test/bin/ffmpe[g]'`
  then kill mediamtx by `pgrep -a mediamtx`.

## MIGRATED TO LUNARIA (LXC 118) — 2026-07-20 ~21:20 ET

The pipeline now runs containerized (kalmia#59 merged → CI created LXC 118
`lunaria` @ 192.168.139.19 → provisioned via `lunaria.yml`): mediamtx +
lunaria-frames (chromium shooter/rotator) + lunaria-stream (ffmpeg), all
systemd `Restart=always` under a service user, credential-free (reads
pub.lan). **Roku app v3 points at 192.168.139.19** — deployed, TV verified
playing from the container. The laptop streaming stack (mediamtx, loops,
encoder) is STOPPED and retired; this workspace remains as the artifact +
the Roku app source. Concept/roadmap: LUNARIA.md (pane-rubric viewport).

All threads closed same night (Chris authorized pve/pve4 work): kalmia#57
deployed on 114 via pub.yml (mappings verified), kalmia#60 merged + replayed
on 118 (clock overlay now ET — verified 22:01 frame), laptop `brief-sync`
timer and streaming stack fully removed.

**Repo created (same night): `lentago/brasenia`** (~/repos/brasenia; created
as `lunaria`, flipped public, then renamed within hours — Lunaria annua is
invasive here, roster is NE natives; brasenia = watershield, floating
leaf-panes). CANONICAL home of the Roku app source (roku-app/ v3, retry
logic), the deploy script (creds via env), and the concept doc
(docs/concept.md). Registered as bullpen project `brasenia`. kalmia's
roles/lunaria + LXC 118 hostname keep the old name pending kalmia#61. The
copies in this workspace are historical artifacts only — edit in the repo.

## End state (2026-07-20 19:35 ET) — superseded by Phase 7/7b, then by the migration above

- Host processes **stopped** (ffmpeg + mediamtx, ports 8554/8888 released).
- **"HLS Pipeline Test" v2 channel left installed on the TV** (operator's
  choice) — it will retry against the dead stream until a future session
  brings the pipeline back. To resume: start mediamtx, then run-stream.sh
  (see Phase progress above for commands); the TV app needs no redeploy.
- To remove the channel later:
  `curl -sS -u rokudev:<pass> --digest -F mysubmit=Delete http://192.168.139.240/plugin_install`
- Gotcha for future sessions: the `out/mediamtx.pid` written by `nohup ... &`
  captured the wrapper PID (off by one) — kill by `pgrep -a mediamtx` instead.
