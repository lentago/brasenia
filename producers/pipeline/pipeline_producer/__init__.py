"""Pipeline producer: turns drosera's pipeline.json into the change-pipeline pane.

Reads ``<url-base>/viewport/pipeline.json`` (schema 1, lentago/drosera#266)
and, while any repo has a change in flight, keeps
``<webroot>/viewport/panes/change-pipeline/{pane.html,manifest.json}`` on the
bus for the compositor (brasenia#27) to rank. Stdlib only, Python 3.9+.
"""
