# Operator Spec: Live RTMP Ingest Validation

**Objective:** Prove the `live` RTMP ingest path (kalmia#102) end-to-end:
a LAN RTMP publisher appears on the TV, the display soaks ≥10 minutes at
acceptable latency, and the display switches automatically between `live` and
`board` when the publisher appears and disappears — before repointing
`VideoScene.xml` from `board` to `live`.

**Receiving agent:** Claude Code, running on a Linux host on the same routable
network as the viewport LXC (`lunaria`, LXC 118 on pve4) and the Roku TV.

**Success criteria (overall):**

- Roku displays a live DJI Fly stream on the `live` path
- Glass-to-glass latency measured and recorded (expected 10–20 s; acceptable
  for household display: anything under 30 s)
- Stream soaks ≥10 minutes without stall or artifact
- Publisher drop → display switches to `board` automatically (retry handler
  fires), within 10 s of error state
- Publisher rejoin → display switches back to `live` automatically, within one
  HLS segment join cycle (typically 10–20 s)
- If switchover fails: failure mode documented; v0 fallback (manual repoint to
  `live` via `lunaria_tv_url` recipe) noted as the contingency and ADR-0007
  updated with the outcome

**Out of scope:** compositor integration (Phase 2), recording to disk,
multi-publisher priority testing, Cast client validation on the live path.

---

## Phase 0 — Operator prerequisites (HUMAN — verify before starting)

The agent cannot perform these. Halt and ask the operator if any are
unconfirmed.

| # | Prerequisite | How |
|---|---|---|
| 0.1 | kalmia#102 merged and deployed | Confirm with operator: `ssh lunaria systemctl status mediamtx` shows the service running post-deploy |
| 0.2 | mediamtx `live` path configured with fallback to `board` | Visible in kalmia#102 diff; agent will verify via API in Phase 1 |
| 0.3 | `MEDIAMTX_API` known | LXC 118 LAN IP + port, e.g. `http://10.x.x.118:9997` — confirm with operator |
| 0.4 | `ROKU_IP` known | Roku Settings → Network → About, or from the existing deploy script env |
| 0.5 | `ROKU_DEV_PASS` known | The dev password set when developer mode was enabled (Chris has it) |
| 0.6 | Roku developer mode enabled and TV powered on | Confirm before starting |
| 0.7 | DJI Fly app configured with custom RTMP URL | URL format: `rtmp://pub.lan:1935/live?<publish-token>` — operator has the token from kalmia secrets |
| 0.8 | Phone on home Wi-Fi, drone powered on | RC-N-series: phone handles Wi-Fi independently of the RC link |
| 0.9 | `board` stream is live on the LXC (current production state) | Confirms the baseline before the test touches anything |

Record all confirmed values in a `NOTES.md` in the workspace before proceeding.

---

## Phase 1 — Verify mediamtx `live` path and fallback config

**Actions:**

```bash
# Confirm mediamtx API is reachable and lists the expected paths
curl -s "${MEDIAMTX_API}/v3/paths/list" | python3 -m json.tool
```

Inspect the output. Confirm:
- A path named `live` is present in the path list
- A path named `board` is present
- `live` has a `fallback` entry pointing at `board` (or the equivalent in
  the mediamtx v3 API response — field name may be `source` or nested
  depending on version; look for the board fallback reference)

```bash
# Confirm board has a publisher (the production stream is live)
curl -s "${MEDIAMTX_API}/v3/paths/get/board" | python3 -m json.tool
```

**Acceptance:**

- Both paths present in API response
- `board` path shows an active source/publisher
- `live` path shows no publisher (pre-test baseline)
- Fallback relationship visible in `live` path config

**Failure branch:**

- API unreachable → kalmia#102 not deployed, or `MEDIAMTX_API` address wrong;
  halt and ask operator
- `live` path absent → deployment incomplete; halt
- `live` has a publisher already → unexpected; ask operator to confirm state
  before proceeding

---

## Phase 2 — Baseline: Roku on `board` (production sanity check)

The production Roku channel is currently pointed at `board`. Confirm playback
before any test changes.

**Actions (HUMAN-IN-LOOP):**

Direct the operator:

1. Confirm the TV is showing the `board` stream (morning brief or test pattern)
2. Confirm playback is stable — no buffering, no black screen

Record in `NOTES.md`: board baseline confirmed, timestamp.

**Agent action:**

```bash
# Cross-check: board path active in mediamtx
curl -s "${MEDIAMTX_API}/v3/paths/get/board" | python3 -m json.tool
```

Confirm the `ready` or `source` field shows an active publisher.

**Acceptance:**

- Operator confirms stable `board` playback on TV
- API confirms active publisher on `board`

---

## Phase 3 — Build and sideload test channel pointing at `live`

The production channel targets `board`. For validation, sideload a test
build targeting `live?cookieCheck=1`. This is the exact URL change that will
become the production commit once this spec passes.

**Actions:**

Navigate to the `roku-app/` directory in the brasenia repo checkout on the
LXC (or the agent's working host — wherever the repo is available and
`ROKU_IP`/`ROKU_DEV_PASS` are set):

```bash
cd <brasenia-repo>/roku-app
```

Verify `components/VideoScene.xml` currently contains the `board` URL:

```bash
grep -n 'url\|board\|live' components/VideoScene.xml
```

The `content.url` line should reference `board`. Confirm `?cookieCheck=1` is
present.

Create the test build by copying `VideoScene.xml` with `board` replaced by
`live`, keeping `?cookieCheck=1` and the retry handler untouched:

```bash
# Work in a temp directory to avoid touching the production source
mkdir -p /tmp/live-ingest-test && cp -r . /tmp/live-ingest-test/roku-app
sed -i 's|/board/index\.m3u8|/live/index.m3u8|g' \
  /tmp/live-ingest-test/roku-app/components/VideoScene.xml

# Verify the substitution and that nothing else changed
grep 'url' /tmp/live-ingest-test/roku-app/components/VideoScene.xml
diff components/VideoScene.xml \
  /tmp/live-ingest-test/roku-app/components/VideoScene.xml
```

Confirm the diff shows exactly one line changed (the URL), `?cookieCheck=1`
still present, and the retry handler (`observeField`, `Timer`) untouched.

Build and sideload:

```bash
cd /tmp/live-ingest-test/roku-app
zip -r /tmp/live-ingest-test.zip . -x '.*'
curl -sS -u "rokudev:${ROKU_DEV_PASS}" --digest \
  -F "mysubmit=Install" \
  -F "archive=@/tmp/live-ingest-test.zip" \
  "http://${ROKU_IP}/plugin_install" | grep -oE 'Install (Success|Failure[^<]*)' || true
```

**Acceptance:**

- Installer response contains `Install Success`
- The diff shows exactly one line changed in `VideoScene.xml`

**Failure branches:**

- `401` → wrong dev password or digest auth missing
- `Install Failure: no manifest` → zip structure wrong; manifest must be at
  zip root (the `cd roku-app` + `zip .` pattern puts it there)
- Retry handler lines missing from diff check → stop; do not sideload a build
  without the retry handler

---

## Phase 4 — Publisher join: live stream appears on TV (HUMAN-IN-LOOP)

**Operator actions:**

1. In DJI Fly, start a live stream to the configured RTMP URL. Confirm the app
   shows "Live" status and a rising bit-rate counter.
2. Wait for the TV to switch to the live feed. Record the time from DJI Fly
   showing "Live" to the TV showing the drone's camera view.

**Agent actions (run concurrently — poll until publisher appears):**

```bash
# Poll mediamtx until live path shows a publisher (30 s timeout)
for i in $(seq 1 30); do
  state=$(curl -s "${MEDIAMTX_API}/v3/paths/get/live" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('ready','false'))" 2>/dev/null)
  echo "$(date +%T) live ready=$state"
  [ "$state" = "True" ] || [ "$state" = "true" ] && break
  sleep 1
done
```

Once publisher confirmed by API, ask the operator:

- Is the drone camera visible on the TV? (y/n)
- What is the glass-to-glass latency? (compare drone video timestamp or
  on-screen motion against phone clock; expected 10–20 s)

Record in `NOTES.md`: publisher join time (UTC), TV appearance confirmed,
measured latency.

**Acceptance:**

- mediamtx API shows `live` path ready with a publisher
- Operator confirms drone video on TV
- Latency ≤ 30 s (acceptable); record actual value

---

## Phase 5 — Soak: ≥10 minutes of live publish (HUMAN-IN-LOOP)

**Operator actions:**

Leave DJI Fly streaming. Note start time. Watch the TV periodically over the
next 10+ minutes.

**Agent actions:**

Poll mediamtx API every 60 s to confirm the `live` path remains active. Log
each poll result to `NOTES.md`.

```bash
# Soak poll — run for 12 minutes (720 s), sampling every 60 s
for i in $(seq 1 12); do
  state=$(curl -s "${MEDIAMTX_API}/v3/paths/get/live" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('ready','?'))" 2>/dev/null)
  echo "$(date +%T) soak check $i/12: live ready=$state"
  sleep 60
done
```

After 10+ minutes, ask the operator:

- Any stalls, buffering events, or black-screen moments? (y/n; describe if y)
- TV still showing drone video? (y/n)

Record in `NOTES.md`.

**Acceptance:**

- All API polls show `live` path active
- Operator reports no stalls or artifacts over ≥10 minutes
- TV still showing live feed at soak end

---

## Phase 6 — Publisher drop: display falls back to `board`

This phase validates the critical switchover: when the publisher stops, does
the Roku automatically return to the `board` stream via the retry handler +
mediamtx fallback wiring?

**Operator actions:**

1. In DJI Fly, stop the live stream. Note the stop time.
2. Watch the TV. The sequence should be:
   - DJI Fly stops → mediamtx drops the `live` publisher
   - Roku's next HLS segment fetch fails → Roku enters error state
   - ADR-0002 retry handler fires within ~3 s → Roku rejoins `live/index.m3u8`
   - mediamtx serves `board` (fallback, no publisher on `live`) → `board`
     appears on TV
3. Record time from DJI Fly stop to `board` appearing on TV.

**Agent actions:**

```bash
# Poll until live publisher drops
for i in $(seq 1 30); do
  state=$(curl -s "${MEDIAMTX_API}/v3/paths/get/live" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('ready','?'))" 2>/dev/null)
  echo "$(date +%T) live ready=$state"
  [ "$state" = "False" ] || [ "$state" = "false" ] && break
  sleep 1
done
echo "$(date +%T) live publisher gone — waiting for board to appear on TV"
```

Ask the operator: did `board` appear on the TV? How many seconds after DJI
Fly stopped? Record in `NOTES.md`.

**Acceptance:**

- mediamtx confirms `live` publisher gone within seconds of DJI Fly stop
- Operator confirms `board` appeared on TV, within 10 s of publisher drop
  (3 s retry fire + HLS join)

**Failure branch — switchover does not work:**

If the TV goes black and stays black, or shows a persistent error state and
does not return to `board`:
1. Record the failure mode in `NOTES.md` (e.g., black screen, error overlay,
   specific behavior observed).
2. Restore the TV manually: reinstall the production channel (Phase 8, path A)
   to get `board` back.
3. Note this outcome in `NOTES.md` and flag for ADR-0007 update. The
   contingency for v0 in this case is a manual `lunaria_tv_url` recipe repoint
   to `live` (operator sets a runtime URL variable) rather than a compiled
   channel change, bypassing the fallback switching entirely.
4. Do not proceed to Phase 7 if Phase 6 fails.

---

## Phase 7 — Publisher rejoin: display switches back to `live`

With the TV on `board`, confirm that restarting the DJI Fly stream returns
the TV to `live` without any Roku interaction.

**Operator actions:**

1. Restart the DJI Fly live stream (same RTMP URL as Phase 4).
2. Watch the TV. Expected sequence:
   - DJI Fly publishes → mediamtx serves `live` on `live/index.m3u8`
   - Roku's next HLS segment fetch gets `live` segments transparently
   - TV switches to drone camera view within one segment boundary cycle
     (typically 10–20 s, matching the join latency from Phase 4)
3. Record time from DJI Fly "Live" to TV showing drone view.

**Agent actions:**

```bash
# Poll until live publisher returns
for i in $(seq 1 60); do
  state=$(curl -s "${MEDIAMTX_API}/v3/paths/get/live" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('ready','?'))" 2>/dev/null)
  echo "$(date +%T) live ready=$state"
  [ "$state" = "True" ] || [ "$state" = "true" ] && break
  sleep 1
done
```

Ask the operator: did the TV switch back to the drone view? How many seconds?

**Note on `?cookieCheck=1` and path-to-path transitions:** ADR-0001 documents
that mediamtx ≥1.19 302-redirects without `?cookieCheck=1` and Roku's HLS
client does not follow the session dance reliably. The `live/index.m3u8` URL
in the test build includes `?cookieCheck=1`; the concern here is whether the
transition from `board` segments back to `live` segments (within the same
playlist URL) triggers any cookie-session edge case. Record whether any
buffering or black-screen events accompany the rejoin.

Record in `NOTES.md`: rejoin time, any buffering events, whether `?cookieCheck=1`
appeared to affect the transition.

**Acceptance:**

- Operator confirms TV switched back to drone view
- Switchover time ≤ 30 s (one HLS join cycle; faster is better)
- No persistent black screen or error requiring manual intervention

---

## Phase 8 — Results, assessment, and channel restore

### 8A — If all phases passed (restore production channel)

Reinstall the production channel (the `board`-targeted build from the repo):

```bash
cd <brasenia-repo>
ROKU_IP="${ROKU_IP}" ROKU_DEV_PASS="${ROKU_DEV_PASS}" \
  bash scripts/deploy-roku.sh
```

Confirm `Install Success` and that the TV returns to the `board` stream.

Clean up the test build:

```bash
rm -rf /tmp/live-ingest-test /tmp/live-ingest-test.zip
```

Write a final summary to `NOTES.md`:

```
PASS — live-ingest-spec.md validation complete
Date: <UTC timestamp>
Join latency: <measured, Phase 4>
Soak: <duration, Phase 5>
Publisher-drop switchover: <seconds, Phase 6>
Publisher-rejoin switchover: <seconds, Phase 7>
cookieCheck notes: <any edge cases or "none observed">
Verdict: proceed with VideoScene.xml repoint to live (scope item 4, issue #17)
```

### 8B — If Phase 6 or 7 failed (fallback contingency)

Reinstall the production channel first (same `deploy-roku.sh` command above).

Write to `NOTES.md`:

```
FAIL — fallback switching did not work
Date: <UTC timestamp>
Failure mode: <description>
Phase failed: 6 / 7 / both
Contingency: lunaria_tv_url recipe repoint OR keep board + manual swap
Next step: update ADR-0007 with observed outcome
```

Do not merge the VideoScene.xml repoint (scope item 4 of issue #17) until the
failure mode is understood and a path forward is agreed.

---

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| mediamtx API unreachable | kalmia#102 not deployed, or wrong IP | Confirm with operator; check `MEDIAMTX_API` |
| `live` path absent from API | Deployment incomplete | Re-deploy kalmia#102 |
| DJI Fly shows error, no stream | Wrong RTMP URL or bad publish token | Verify URL format with operator; check kalmia secrets |
| TV black after Phase 3 sideload | Test channel failed to install | Reinstall production channel and check Phase 3 failure branches |
| TV stays on `live` after publisher drop | Fallback config not applied in mediamtx | Check kalmia#102 mediamtx config; may be `sourceOnDemand`/fallback field issue |
| TV stays on `board` after publisher rejoin | Normal — takes up to one HLS segment cycle | Wait 20 s before calling it a failure |
| Black screen on rejoin (not `board`, not `live`) | `?cookieCheck=1` session dance edge case on path transition | Record the behavior; test whether removing/adding `?cookieCheck=1` from the test URL changes it |
| `Install Failure: no manifest` | Zip structure | Manifest must be at zip root; check `cd roku-app && zip .` pattern |
