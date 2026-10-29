# ADR-0015: Cap the Roku's lag by rejoining the stream

**Status:** Accepted (2026-10-29; #95, lentago/kalmia#193). Amends
[ADR-0009](0009-office-roku-4k-hevc-over-ffmpeg-hls.md): the playlist is 3
segments long, not 7.

## Context

On 2026-10-29 the office Roku was playing about 20 s behind LXC 118's
encoder. Three samples 20 s apart found the same lag each time. That is more
than the rest of the pipeline put together: the compositor and the shooter
take 5–9 s from a decision to a new frame. The samples compared the segment
the Roku reported playing (ECP `query/media-player`) with the newest segment
in `index.m3u8`.

Tests on the device the same day, pausing the encoder (`SIGSTOP`) to mimic a
stall, found two causes:

- **Join depth.** On the 7-segment playlist (14 s), a fresh join landed
  anywhere from 4 to 14 s behind.
- **Drift.** A stall long enough to empty the player's buffer makes it
  rebuffer, and it then resumes from where it stopped. A 12 s stall left it
  6–12 s further behind, and Roku's player never catches up on a live stream
  by itself. Stalls add up: 20 s was where this build-up had got to.

Seeking back to the live edge did not work. Roku's guidance is to seek a
live stream to 999999 and let the player clip it to the live edge with "a
robust buffer"; Roku also asks apps to stay at least 30 s from the edge. On
a 14 s playlist, both a seek to 999999 and a seek to `duration - 6` landed
near the oldest segment, about 18–20 s behind, so every seek made the lag
worse.

## Decision

- **LXC 118's playlist is 3 segments (6 s) long** (kalmia#193). That is the
  HLS minimum of three target durations. A fresh join then lands 4–6 s
  behind the newest segment.
- **The app checks its lag every 15 s and rejoins when it drifts.** The lag
  is `duration - position` on the Video node, the same figure ECP reports.
  Two checks in a row over 8 s stop playback and start it again, the same
  way the retry handler does. The rejoin lands back at 4–6 s.
- **The app never seeks.**

## Consequences

- **A change reaches the screen about 6 s after the encoder writes it**,
  down from 20 s. After a stall the lag recovers within about 30 s.
- **A rejoin blanks the screen briefly.** It happens only after a stall that
  left the player behind, never in steady playback.
- **The guard depends on the short playlist.** On a 7-segment playlist a
  fresh join could land more than 8 s behind, and the app would keep
  rejoining. The two changes ship together.
- **A 3-segment playlist leaves the player less margin** for Wi-Fi hiccups.
  None showed up in testing (about 39 Mbps measured for a 6 Mbps stream).
  If rebuffers become common, lengthen the playlist and raise the threshold
  together.

## Alternatives considered

- **Seek to the live edge.** Rejected: on this playlist Roku clamps live
  seeks near the oldest segment (see Context).
- **A short playlist alone.** Rejected: it fixes join depth but not drift.
  After stalls the Roku played 8–12 s behind, beyond the 3-segment window,
  because the lag sits in its own buffer.
- **Low-Latency HLS.** Not tried: ffmpeg's HLS muxer does not write it, and
  ADR-0009 moved off mediamtx because the Roku rejected its fMP4 playlists.
