"""Focus producer: turns fresh session beacons into one open-PRs pane per repo.

Reads beacons from ``<webroot>/viewport/focus/``, fetches each repo's open
pull requests from the unauthenticated GitHub REST API, and writes
``<webroot>/viewport/panes/focus-<owner>-<name>/{pane.html,manifest.json}``
for the compositor (brasenia#27) to rank. Stdlib only, Python 3.9+.
"""
