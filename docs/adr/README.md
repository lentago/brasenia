# Architecture decision records

Reconstructed 2026-08-13 from this repo's commit history, issues/PRs,
`CLAUDE.md`, and the 2026-07-20 Roku HLS validation session
(`docs/roku-hls-test-spec.md`, `docs/validation-notes-2026-07-20.md`). These
decisions were made and acted on at the time but never written up as ADRs;
this index and the records below fill that gap after the fact. The date in
each record's Status line is the *original* decision date, not the
reconstruction date. Each record's Alternatives section separates what was
actually weighed at the time from options marked *"retrospective — not
considered at the time"* — those are this reconstruction's own honest
assessment, not something argued over in the room that night.

Records from ADR-0006 onward are contemporaneous — written when the
decision was made, not reconstructed.

| ADR | Decision | Date |
|---|---|---|
| [0001](0001-roku-native-hls-over-decoder-hardware.md) | Consumer Roku TV + LAN HLS over dedicated decoder hardware | 2026-07-20 |
| [0002](0002-mandatory-client-side-retry-handler.md) | The retry handler is the product | 2026-07-20 |
| [0003](0003-rubric-driven-selection-compositor-sole-writer.md) | Rubric-driven pane selection; the compositor is the sole screen writer | 2026-07-20 |
| [0004](0004-nas-file-pane-bus-write-then-rename.md) | Pane bus is NAS files with write-then-rename, manifest, and a TTL backstop | 2026-07-20 |
| [0005](0005-product-runtime-split-with-kalmia.md) | Product/runtime split with kalmia, enforced in both directions | 2026-07-20 |
| [0006](0006-cast-web-receiver-second-client.md) | Chromecast web receiver as a second client; the compositor's output becomes a decision (superseded by 0010) | 2026-08-14 |
| [0007](0007-live-rtmp-ingest-generic-path.md) | Generic RTMP ingest path; fallback-chain switching; `live` as rubric source type (retired 2026-10-29, kalmia#213) | 2026-08-16 |
| [0008](0008-compositor-and-producers-on-pub.md) | The compositor and the producers run on pub; the display guest stays a client (amended by 0014) | 2026-10-07 |
| [0009](0009-office-roku-4k-hevc-over-ffmpeg-hls.md) | The office Roku plays 4K HEVC from ffmpeg-written HLS; the play-room Roku is retired | 2026-10-28 |
| [0010](0010-roku-is-the-client-platform.md) | Roku is the client platform; the Cast client is retired | 2026-10-28 |
| [0011](0011-rubric-settings-on-the-share.md) | Rubric settings are household overrides on the share, written through pub-signals | 2026-10-28 |
| [0012](0012-the-remote-peeks-it-never-decides.md) | The Roku remote peeks; it never decides (amended by 0013) | 2026-10-28 |
| [0013](0013-the-remote-sets-the-default-resting-pane.md) | The remote sets the household's default resting pane | 2026-10-28 |
| [0014](0014-home-and-fleet-feed-resting-panes.md) | Home Assistant and the job queue feed resting panes; pub holds the token (amends 0008; amended by 0017) | 2026-10-28 |
| [0015](0015-cap-the-roku-lag-by-rejoining.md) | Cap the Roku's lag by rejoining the stream; the playlist is 3 segments (amends 0009) | 2026-10-29 |
| [0016](0016-panes-carry-a-revision-and-may-link-a-web-page.md) | Panes carry a content revision; a pane may link a web page (off until the renderer is ready) | 2026-10-29 |
| [0017](0017-grafana-panes-rendered-on-pub.md) | Grafana dashboards are rendered on pub into ordinary panes with a Viewer token (amends 0014) | 2026-10-29 |
| [0018](0018-standing-slots-are-household-settings.md) | Standing slots are household settings, kept on the bus by a producer | 2026-10-29 |
| [0019](0019-panes-on-a-1920x1080-canvas-with-a-30px-floor.md) | Panes are laid out on a 1920×1080 canvas at 2×, with a 30 px text floor; "band" names the screenful (amends 0009) | 2026-10-29 |
