# Operator Spec: Roku Native HLS Validation

**Objective:** Prove the pipeline `LAN host (ffmpeg) → mediamtx (HLS) → Roku TV (sideloaded dev channel)` works end-to-end, with measured glass-to-glass latency, before purchasing dedicated HDMI decoder hardware.

**Receiving agent:** Claude Code, running on a Linux host on the same routable network as the Roku TV. Debian/Ubuntu LXC on Proxmox or Fedora laptop both acceptable.

**Success criteria (overall):**
- Roku displays a live test-pattern stream with a burned-in wall-clock timestamp
- Timestamp advances smoothly for 10+ minutes without stall or artifact
- Glass-to-glass latency measured and recorded (expected: 6-15s; acceptable for dashboard use: anything under 30s)
- Full pipeline survives a stream restart (kill/restart ffmpeg) with automatic recovery on the Roku

**Out of scope:** Grafana rendering (Phase 7 sketch only, not part of acceptance), decoder box evaluation, permanent deployment.

---

## Phase 0 - Operator prerequisites (HUMAN - verify before starting)

The agent cannot perform these. Halt and ask the operator if any are unconfirmed.

| # | Prerequisite | How |
|---|---|---|
| 0.1 | Roku Developer Mode enabled | On Roku remote: Home ×3, Up ×2, Right, Left, Right, Left, Right. Follow on-screen setup, set dev password. TV reboots. |
| 0.2 | `ROKU_IP` known | Shown on the dev mode enablement screen, or Roku Settings → Network → About |
| 0.3 | `ROKU_DEV_PASS` known | Set during 0.1 |
| 0.4 | `HOST_IP` known | LAN IP of the host running this spec (`ip -4 addr`) |
| 0.5 | Network path open, Roku → host | Roku must reach `HOST_IP:8888` (HLS pull). **If the Roku is on an IoT VLAN and the host is not, IoT→LAN on tcp/8888 must be allowed at the Firewalla.** Confirm with operator. |
| 0.6 | Network path open, host → Roku | Host must reach `ROKU_IP:80` (dev installer). Usually open LAN→IoT. |
| 0.7 | TV powered on, not asleep | Sideload auto-launches the app; screen must be awake to verify |

Record all values at the top of a `NOTES.md` in the workspace before proceeding.

---

## Phase 1 - Workspace and dependencies

**Actions:**

```bash
mkdir -p ~/roku-hls-test/{mediamtx,stream,roku-app/source,roku-app/components,scripts,out}
cd ~/roku-hls-test
```

Install dependencies (adapt to distro):

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg curl zip fontconfig fonts-dejavu-core
# Fedora
sudo dnf install -y ffmpeg curl zip fontconfig dejavu-sans-fonts
```

Note: Fedora may require RPM Fusion for full ffmpeg (libx264). If `ffmpeg -encoders | grep libx264` returns nothing, enable RPM Fusion free repo first.

If host runs firewalld (Fedora default):

```bash
sudo firewall-cmd --add-port=8888/tcp --add-port=8554/tcp
```

(Session-only rule is fine; this is a test.)

**Acceptance:**
- `ffmpeg -version` succeeds and `ffmpeg -encoders | grep libx264` shows the encoder
- Directory tree exists as above

---

## Phase 2 - mediamtx

**Actions:**

Download latest linux_amd64 release from https://github.com/bluenviron/mediamtx/releases (grab the current version tag; do not hardcode a stale one):

```bash
cd ~/roku-hls-test/mediamtx
# Example - substitute current release URL:
curl -LO https://github.com/bluenviron/mediamtx/releases/download/vX.Y.Z/mediamtx_vX.Y.Z_linux_amd64.tar.gz
tar xzf mediamtx_*.tar.gz
```

Create `mediamtx/mediamtx.yml` (replace the shipped default):

```yaml
# Roku HLS test config - minimal
hls: yes
hlsAddress: :8888
hlsVariant: mpegts        # CRITICAL: Roku compatibility. Default lowLatency
                          # uses LL-HLS/fMP4 which Roku handles poorly.
hlsSegmentDuration: 2s
hlsSegmentCount: 7
hlsAlwaysRemux: yes       # remux continuously so first client join is fast

rtsp: yes
rtspAddress: :8554

paths:
  board:                  # named 'board', not 'dash' - avoid MPEG-DASH confusion
```

Run it (foreground in a dedicated terminal, or backgrounded with logs captured):

```bash
cd ~/roku-hls-test/mediamtx && ./mediamtx mediamtx.yml
```

**Acceptance:**
- `ss -tlnp | grep -E '8554|8888'` shows both ports listening
- mediamtx log shows no errors, HLS server started

---

## Phase 3 - Test stream

**Actions:**

Create `stream/run-stream.sh`:

```bash
#!/usr/bin/env bash
# Test pattern + wall-clock overlay, pushed to mediamtx via RTSP.
# H.264 main profile, yuv420p, AAC silent audio - maximum Roku compatibility.
set -euo pipefail

ffmpeg -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=48000" \
  -vf "drawtext=text='%{localtime\:%X}':fontsize=72:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=40:y=40" \
  -c:v libx264 -preset veryfast -tune zerolatency \
  -profile:v main -pix_fmt yuv420p \
  -g 60 -keyint_min 60 -sc_threshold 0 -b:v 3000k \
  -c:a aac -b:a 64k \
  -f rtsp rtsp://localhost:8554/board
```

```bash
chmod +x stream/run-stream.sh && ./stream/run-stream.sh
```

If `drawtext` errors on font resolution, add `fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (Debian) or the Fedora equivalent path to the filter.

**Acceptance:**
- ffmpeg runs continuously, reporting ~30fps, no repeated warnings
- mediamtx log shows the `board` path receiving a publisher
- `curl -s http://localhost:8888/board/index.m3u8` returns a valid M3U8 playlist referencing `.ts` segments (mpegts variant confirmed)

---

## Phase 4 - HLS reachability from a second device

The Roku will pull from `HOST_IP`, not localhost. Validate the real path first.

**Actions:**
- `curl -s http://HOST_IP:8888/board/index.m3u8` from the host itself using the LAN IP (catches firewalld binding issues)
- If a second device is available (operator's phone on same/IoT network via VLC, or another LXC), confirm playback of `http://HOST_IP:8888/board/index.m3u8`. If the Roku is on an IoT VLAN, the second-device test should run from that VLAN to validate the Firewalla rule from Phase 0.5.

**Acceptance:**
- Manifest retrievable via `HOST_IP` (not just localhost)
- If second-device playback tested: video plays with timestamp advancing

---

## Phase 5 - Roku dev channel: build and deploy

**Actions:**

Create `roku-app/manifest`:

```
title=HLS Pipeline Test
major_version=1
minor_version=0
build_version=1
ui_resolutions=hd
```

Create `roku-app/source/main.brs`:

```brightscript
sub Main()
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.SetMessagePort(port)
    scene = screen.CreateScene("VideoScene")
    screen.Show()
    while true
        msg = wait(0, port)
        if type(msg) = "roSGScreenEvent"
            if msg.IsScreenClosed() then return
        end if
    end while
end sub
```

Create `roku-app/components/VideoScene.xml` - **substitute the real HOST_IP**:

```xml
<?xml version="1.0" encoding="utf-8" ?>
<component name="VideoScene" extends="Scene">
  <script type="text/brightscript">
    <![CDATA[
    sub init()
        video = m.top.findNode("player")
        content = CreateObject("roSGNode", "ContentNode")
        content.url = "http://HOST_IP:8888/board/index.m3u8"
        content.streamformat = "hls"
        content.live = true
        video.content = content
        video.control = "play"
        video.setFocus(true)
    end sub
    ]]>
  </script>
  <children>
    <Video id="player" width="1280" height="720" translation="[0,0]" />
  </children>
</component>
```

Create `scripts/deploy-roku.sh`:

```bash
#!/usr/bin/env bash
# Zip the app (manifest MUST be at zip root) and sideload via Roku dev installer.
set -euo pipefail
: "${ROKU_IP:?set ROKU_IP}" "${ROKU_DEV_PASS:?set ROKU_DEV_PASS}"

cd "$(dirname "$0")/../roku-app"
rm -f ../out/hls-test.zip
zip -r ../out/hls-test.zip . -x '.*'

curl -sS -u "rokudev:${ROKU_DEV_PASS}" --digest \
  -F "mysubmit=Install" \
  -F "archive=@../out/hls-test.zip" \
  "http://${ROKU_IP}/plugin_install" | grep -oE 'Install (Success|Failure[^<]*)' || true
```

Deploy:

```bash
chmod +x scripts/deploy-roku.sh
ROKU_IP=<from Phase 0> ROKU_DEV_PASS=<from Phase 0> ./scripts/deploy-roku.sh
```

**Acceptance:**
- Installer response contains `Install Success` (or `Identical to previous version` on redeploy)
- Sideloaded channels auto-launch: TV should switch to the app within seconds of install

**Failure branches:**
- `401` → wrong dev password or digest auth flag missing
- `Install Failure: no manifest` → manifest not at zip root; verify zip was built from inside `roku-app/`
- Connection refused on port 80 → dev mode not enabled, or host→Roku path blocked

---

## Phase 6 - On-glass validation and latency measurement (HUMAN-IN-LOOP)

The agent cannot see the TV. Direct the operator through:

1. **Playback check:** test pattern visible, timestamp overlay advancing smoothly.
2. **Latency:** operator compares overlay clock against the host's actual clock (run `watch -n 0.5 date +%X` on the host, or use a phone synced to NTP). Record delta in `NOTES.md`. Expected 6-15s.
3. **Soak:** leave running 10+ minutes. Record any stalls, artifacts, or buffering events.
4. **Recovery test:** kill ffmpeg (`Ctrl-C`), wait 10s, restart `run-stream.sh`. Record Roku behavior: does playback resume unassisted, and how long does recovery take? (mediamtx stays up throughout - this simulates a renderer restart.)

**Acceptance:**
- All four checks recorded in `NOTES.md` with observed values
- Recovery either automatic, or failure mode documented (this directly informs the buy/no-buy decision on decoder hardware)

---

## Phase 7 - OPTIONAL STRETCH (not part of acceptance): real dashboard source

Do not start unless the operator explicitly asks. Sketch for the follow-on session:

Replace `testsrc2` with a headless Chromium render of Grafana:

```bash
# Xvfb virtual display + kiosk Chromium + x11grab capture
Xvfb :99 -screen 0 1280x720x24 &
DISPLAY=:99 chromium --kiosk --no-first-run 'https://<grafana>/d/<dash>?kiosk' &
ffmpeg -f x11grab -framerate 15 -video_size 1280x720 -i :99 \
  -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
  -g 30 -b:v 2500k -an \
  -f rtsp rtsp://localhost:8554/board
```

Same mediamtx and Roku app, zero changes downstream - that decoupling is the point of the architecture. Grafana auth for a headless session (API-key-in-URL vs service account vs anonymous org access) is its own design decision; park it for the next session.

---

## Phase 8 - Teardown

```bash
# Remove sideloaded channel
curl -sS -u "rokudev:${ROKU_DEV_PASS}" --digest \
  -F "mysubmit=Delete" "http://${ROKU_IP}/plugin_install" >/dev/null
# Stop ffmpeg and mediamtx (Ctrl-C / kill)
# Remove session firewalld rules if added (they expire on reload anyway)
```

Leave `~/roku-hls-test/` intact - it is the artifact. If results are positive, this workspace seeds a proper repo (`pitzilabs/dashboard-pipeline` or similar) in a later session.

---

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| Roku black screen, no error | Encoder profile/pixel format | Confirm `-profile:v main -pix_fmt yuv420p` |
| Roku buffers endlessly | LL-HLS variant served | Confirm `hlsVariant: mpegts` in mediamtx.yml and restart |
| Manifest 404 | Path mismatch or no publisher | Path is `board` end-to-end; ffmpeg must be running |
| Manifest OK on localhost, Roku fails | firewalld or VLAN block | Phase 1 firewall-cmd; Phase 0.5 Firewalla rule |
| drawtext error | Font not resolved | Add explicit `fontfile=` path |
| Choppy playback | Undersized segments/count | Raise `hlsSegmentCount` to 10; drop `-b:v` to 2000k |
| Install Failure: no manifest | Zip structure | Manifest must be at zip root |
