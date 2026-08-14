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

| ADR | Decision | Date |
|---|---|---|
| [0001](0001-roku-native-hls-over-decoder-hardware.md) | Consumer Roku TV + LAN HLS over dedicated decoder hardware | 2026-07-20 |
| [0002](0002-mandatory-client-side-retry-handler.md) | The retry handler is the product | 2026-07-20 |
| [0003](0003-rubric-driven-selection-compositor-sole-writer.md) | Rubric-driven pane selection; the compositor is the sole screen writer | 2026-07-20 |
| [0004](0004-nas-file-pane-bus-write-then-rename.md) | Pane bus is NAS files with write-then-rename, manifest, and a TTL backstop | 2026-07-20 |
| [0005](0005-product-runtime-split-with-kalmia.md) | Product/runtime split with kalmia, enforced in both directions | 2026-07-20 |
