"""PRs producer: the fleet's pull requests as a running list (brasenia#134).

Reads GitHub's search API without a token (every ``lentago`` repository is
public) and keeps one resting pane on the bus:
``<webroot>/viewport/panes/prs/``. It shows how many pull requests are open,
opened today and merged today, over the latest events, newest first: each
one's status (open, draft, merged, closed), repo and number, title, who
opened it, and how long ago. Stdlib only, Python 3.11+.
"""
