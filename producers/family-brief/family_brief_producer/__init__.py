"""Family brief producer: turns the Family Brief document into a today-and-tomorrow pane.

Reads ``<source>`` (default ``http://pub.lan/family-brief/latest.json``, schema 1,
written each morning by the Family Brief routine) and, while that brief is
fresh, keeps ``<webroot>/viewport/panes/family-today/{pane.html,manifest.json}``
on the bus for the compositor (brasenia#27) to rank. Stdlib only, Python 3.9+.
"""
