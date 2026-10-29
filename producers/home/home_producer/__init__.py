"""Home producer: Home Assistant's states into the home and weather panes.

Reads Home Assistant's REST API with a long-lived token (a systemd credential
on pub, never in git or on the share) and keeps two resting panes on the bus:
``<webroot>/viewport/panes/home/`` (alarm, people, doors and locks, water,
climate) and ``<webroot>/viewport/panes/weather/`` (now, the next day by the
hour, the week) for the compositor to rank (brasenia#86). Stdlib only,
Python 3.11+.
"""
