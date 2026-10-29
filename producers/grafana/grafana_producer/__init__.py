"""Grafana producer: Grafana Cloud dashboards rendered into ordinary panes.

Fetches each configured dashboard from the stack's render API with a Viewer
service-account token (a systemd credential on pub, never in git or on the
share) and keeps one resting pane per slot on the bus: a ``dashboard.png``
and a ``pane.html`` that frames it, so LXC 118 stays credential-free and the
dashboards are never link panes (brasenia#98, ADR-0017). Stdlib only,
Python 3.11+.
"""
