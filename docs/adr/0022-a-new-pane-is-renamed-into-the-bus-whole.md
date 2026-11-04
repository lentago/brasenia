# ADR-0022: A new pane is renamed into the bus whole, and leaves it the same way

**Status:** Accepted (2026-11-04; #51). Amends the bus rules in
[`concept.md`](../concept.md#paths) (write-then-rename, manifest last) and
rule 1 of [`claiming-the-display.md`](../claiming-the-display.md#two-rules).

## Context

Every writer on the viewport bus guards its writes the same way. It reads
`panes/<id>/manifest.json`, checks that `author` is its own or that the pane
does not exist, and then writes `pane.html` and the manifest, each through
write-then-rename. Nothing ties the check to the write. When two writers
check the same pane id while it is absent, both go ahead and write into the
same directory. The one whose manifest lands last owns the pane, and the
other's page can be left under it (#51, raised by CodeRabbit on #48). The
writers are `bin/pane` and all eight producers: family-brief, fleet, focus,
grafana, home, links, pipeline and prs.

Once a pane exists, the race is gone. Every writer refuses a pane whose
manifest names another author, and no writer edits a pane it does not own.
What remains is the moment of creation, and its mirror image: removal is a
`shutil.rmtree` in place, so a reader or another writer can see a pane
directory whose manifest is already deleted. Most producers treat a missing
manifest as "absent", so one could start writing into a directory that its
owner is still deleting.

The cost today is small. The window is milliseconds once per producer cycle,
and producer pane ids normally belong to their producer. But the bus is the
one coordination point between everything that wants the wall, so its
contract should not depend on luck.

## Decision

- **A new pane is built in `viewport/staging/` and renamed into `panes/` in
  one step.** The writer makes `staging/<id>.new.<random>/`, writes every
  file there, manifest last, and calls `rename(staging/<id>.new.<random>,
  panes/<id>)`. A directory rename onto a directory that holds files fails
  (ENOTEMPTY or EEXIST), so of two writers creating the same pane, exactly
  one succeeds, and no reader ever sees a new pane half-written. The loser
  deletes its staging directory, writes nothing, and then treats the pane
  like any existing one: it rewrites the pane if the winner's manifest names
  it as author, and leaves it alone otherwise.
- **An existing pane is rewritten only by its author, as before.** It is
  written file by file through write-then-rename, manifest last. An existing
  pane can't change hands while its author is updating it: another writer
  sees the author and refuses, and its create rename fails.
- **A pane leaves the bus in one step too.** Its author renames
  `panes/<id>` to `staging/<id>.gone.<random>` and deletes it there. Where
  the rename can't be done because the two paths are on different
  filesystems (EXDEV) or the pane directory is a mount point (EBUSY), the
  writer deletes in place, as before.
- **`staging/` is scratch space.** Nothing reads it. The compositor, the
  renderer and `pane ls` scan `panes/` only. A writer that dies between
  building a pane and renaming it leaves one small directory there, which
  is safe to delete once it is a day old.
- **No locks.** Every writer reaches the bus through a CIFS mount of the
  NAS share. That includes the producers on pub, through pve4's mount, and
  `pane` on the workstation. Whether `flock` or byte-range locks hold across
  CIFS clients on different hosts depends on the kernel and the mount
  options, and this was not tested. A lock left by a dead writer also needs
  a timeout, and the timeout reopens the race. The rename is done by the
  server and needs neither.
- **Each producer carries its own copy of the helpers**, as each already
  carries its own `write_atomic`, because the deployed units have no shared
  import path. `bin/pane` holds the reference copy.

The rename semantics were checked on the share itself on 2026-11-04, from
the workstation's CIFS mount (SMB 3.0 to the NAS). A rename onto a missing
directory succeeded. A rename onto a directory holding a file failed with
ENOTEMPTY and left the target untouched. A rename onto an empty directory
replaced it. In 60 races of two processes creating the same pane, every race
had exactly one winner, the loser always got ENOTEMPTY, and the winner's
manifest was the one left in place.

## Consequences

- **The #51 race is closed for every writer in this repo.** A new pane has
  exactly one author from the moment it appears.
- **The focus producer now checks the author before it rewrites a pane.**
  Until now it overwrote any existing `focus-*` pane, whoever owned it, and
  checked the author only before removing one. Rule 1 now holds on its write
  path too.
- **Writers that only update panes they already own are unaffected.** The
  professional-endeavors publish runner (LXC 123) has its two pane
  directories bind-mounted, `search-map` and `search-board`. It never
  creates or removes them, so it needs no change and can't see `staging/`.
- **An empty pane directory carries no claim.** A rename replaces one, which
  is right: it has no manifest and no author.
- **During the rollout, writers on the old contract keep the old race**, and
  nothing worse. A new writer sees a pane an old writer made as an existing
  pane and checks its author. `pane` changes when the workstation clone is
  pulled, and the producers on pub at their next `brasenia-update`.
- **A pane directory without a manifest can now only be debris** left by a
  writer from before this change. Producers keep treating such a directory
  as theirs to rewrite. `pane claim` still refuses one, as it did.

## Alternatives considered

- **A per-pane lock file taken with `flock`** around check-and-write, the
  first option in #51. It needs locking that every CIFS client on every host
  honours, which nobody has shown here. It also needs a stale-lock rule for
  writers that die holding the lock, and that rule reopens the race it was
  meant to close.
- **A generation number in the manifest, checked before the rename**, the
  second option in #51. A file rename overwrites whatever is there, so the
  check and the rename are still two steps, and the window only narrows.
- **`mkdir` as the claim**, with the files written afterwards. That is
  exclusive too, but the directory is visible before its manifest exists,
  and an empty or half-written pane is exactly what readers and writers
  can't interpret.
- **Leave it.** The cost is one lost claim, rarely. But the fix is local to
  the writers, needs no new service and no lock, and makes "a pane appears
  whole" true for every reader as well.
