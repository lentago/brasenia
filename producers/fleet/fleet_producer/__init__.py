"""Fleet producer: the claytonia job queue into the fleet pane.

Reads the bullpen's queue through pub's read-only mount of the claude-jobs
share (workers' heartbeats, claims, the inbox and each run's ``.meta``) and
GitHub's search API for open agent PRs, and keeps one resting pane on the
bus: ``<webroot>/viewport/panes/fleet/`` (brasenia#86). It shows counts,
project names, models and PR titles, never a job's prompt or its logs.
Stdlib only, Python 3.11+.
"""
