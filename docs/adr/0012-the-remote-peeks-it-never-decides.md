# ADR-0012: The Roku remote peeks; it never decides

**Status:** Accepted (2026-10-28; #80)

## Context

Chris asked to step up and down through the panes with the office Roku's
remote. Three things shaped the answer:

- **The rubric decides what is on screen.** [ADR-0003](0003-rubric-driven-selection-compositor-sole-writer.md)
  makes the compositor the only writer of the decision ("a rubric, not a
  remote"). The household tunes that rubric from the configurator
  ([ADR-0011](0011-rubric-settings-on-the-share.md)), not from a button.
- **The 4K stream is slow to change.** A different pane on the stream means
  LXC 118 re-shooting it, encoding it and the Roku joining the new segments.
  That takes roughly 10–20 s ([ADR-0009](0009-office-roku-4k-hevc-over-ffmpeg-hls.md)),
  far too slow for a button that steps.
- **Roku's UI plane tops out at 1080p.** Only the video plane reaches 4K. An
  app can lay its own images over the video, but at 1080p.

## Decision

- **Up and Down peek.** A press shows the next or previous pane at once, as
  a full-screen image over the live video, with a caption naming it ("Up/Down
  2 of 3 · title", and "on screen now" for the one the stream is showing).
  The first press starts from the pane on screen, and steps wrap around.
  Back, or a minute without a press, closes the peek. The stream and the
  compositor's decision are untouched.
- **The compositor publishes what may be peeked at**, `viewport/lineup.json`:
  the live panes in rubric order, then the briefing slot unless a live pane
  already carries the same brief.
- **LXC 118 renders the images.** `lunaria-peek` shoots each line-up item the
  way the stream would (preferring a pane's desk rendition), keeps a
  1920×1080 image and an `index.json`, and serves them at `/peek/` beside the
  stream (kalmia#179). The app polls that index every 15 s.
- **Back no longer exits the channel.** It closes a peek and otherwise does
  nothing, so a stray press can't leave the office on the Roku home screen.
  Home still leaves, because Roku apps can't catch it.
- **The scene, not the Video node, holds focus.** A focused Video answers
  OK, Play and the arrows with trick play, which a live wall should never do.

## Consequences

- **Stepping is instant**, and nobody's button changes what the rubric shows.
- **A peek is 1080p** against the stream's 4K, and up to five minutes old,
  since LXC 118 re-shoots each item every 300 s at a lower priority than the
  encoder. It is fine for "what else is up?" but not as sharp as the live view.
- **LXC 118 shoots one more page per line-up item** every five minutes.
- **Keeping a peeked pane on screen is not possible.** That would need the
  compositor to hold a pane on someone's say-so, a separate decision that
  would amend ADR-0003. If it is ever wanted, the natural trigger is OK on a
  peek.
- **A SceneGraph gotcha is now recorded in the app.** Setting a Timer's
  `control` to `"stop"` and then `"start"` in the same callback left it
  stopped on Roku OS 15.3. `"start"` alone restarts a running timer.

## Alternatives considered

- **Switch the stream on each press.** It would show the chosen pane in 4K,
  but at 10–20 s per step, and it makes the remote a second writer of the
  decision.
- **A compositor hold per press** (pub-signals → compositor → pointer). This
  is the same lag, plus a way around the rubric. It stays the only option if
  keeping a pane on screen is ever wanted.
- **Render the panes in the Roku app.** SceneGraph can't render the HTML
  panes, and they would have to be rebuilt as Roku components.
