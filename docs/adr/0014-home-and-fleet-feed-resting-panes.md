# ADR-0014: Home Assistant and the job queue feed resting panes; pub holds the token

**Status:** Accepted (2026-10-28; #86). **Amended by
[ADR-0020](0020-only-the-rubric-and-the-remote-change-the-wall.md)
(2026-10-29): resting panes no longer take turns**; with no default set, the
first resting pane by id shows. Amends
[ADR-0008](0008-compositor-and-producers-on-pub.md): one producer, the home
producer, holds a credential. Amended by
[ADR-0017](0017-grafana-panes-rendered-on-pub.md): the grafana producer holds
a second, a Viewer token for Grafana Cloud.

## Context

[ADR-0013](0013-the-remote-sets-the-default-resting-pane.md) let the Roku
remote's Left/Right choose the household's default resting pane, and there
were only two to choose from: the Family Brief's today and week. Chris asked
for more positions on that ladder and chose three:

- **Home**: everything Home Assistant knows about the house, with the alarm
  and who is home included ("everything").
- **Weather**: now, the next day and the week, from Home Assistant's weather
  entity.
- **Fleet**: the claytonia bullpen: workers, the queue, the last day's runs,
  and agent PRs awaiting review.

Two of these need data the viewport has never touched. Home Assistant
answers only with a token, and it has no read-only role, so any token can
also unlock doors and disarm the alarm. The job queue is a share pub didn't
mount. ADR-0008 had called a producer that needs a secret "a smell", to be
avoided by pushing the data to pub.lan.

Asked how the Home pane should get its data, Chris chose **pub reads Home
Assistant**, and he approved a **read-only mount** of the job queue on pub.

## Decision

- **The home producer reads Home Assistant's REST API with a long-lived
  token.** The token is a systemd credential of `brasenia-home.service`
  alone (`LoadCredential=` from a root-only file on pub), never in git, on
  the share, in a log or on a page. The producer makes two read calls:
  `GET /api/states`, and `weather.get_forecasts`, a service that only
  answers. The token belongs to a dedicated, non-admin Home Assistant user,
  so it can be revoked without touching anyone's own login. Until the token
  is seeded, the unit is skipped, not failing.
- **The fleet producer reads the job queue through a read-only bind mount**
  (`/srv/claude-jobs` on pub). It opens heartbeats, claim records, run
  `.meta` files and, of a JSON spec, only `project` and `model`. It never
  opens a prompt, a log or a transcript. Open agent PRs come from GitHub's
  search API without a token, so it sees public repositories only.
- **The panes show what was asked for, on a LAN-readable share.** The Home
  pane shows the alarm state, who is home, and which doors are open and
  unlocked. The Fleet pane shows counts, project names, models and PR titles.
- **All three are resting (`ambient`) panes** with a 10-minute TTL. When
  their source goes quiet, they leave the bus instead of showing a stale
  house or queue.
- **Resting panes keep a fixed order, by id.** Each producer rewrites
  `created` on its own cadence. With five resting panes, ranking them by
  `created` would reshuffle their rotation and the remote's order. The
  remote's Left/Right cycles them by id as well, rather than in line-up
  order, which puts the default first.

## Consequences

- **pub holds a token that could operate the house.** It sits in a root-only
  file, is loaded only into the home unit, and is used only for reads. If pub
  is compromised, revoke the token in Home Assistant (the brasenia user's
  profile → Security); nothing else uses it.
- **Anyone on the LAN can read the Home pane** at
  `http://pub.lan/viewport/panes/home/pane.html`: whether the alarm is set,
  who is away, and which doors are open. The household accepted this when it
  asked for everything. A `--hide` list keeps named entities off the pane.
- **pub can read the whole job queue, including prompts**, though the fleet
  producer opens none of them. The mount is read-only, so the viewport can't
  submit a job, and the bullpen's "workers never merge" rule is untouched.
- **ADR-0008's rule narrows** from "no secrets on producers" to "no secrets
  without an ADR". Other producers stay credential-free.
- **Nothing on screen moves on its own.** The household's default resting
  pane (family-today) holds as before; the new panes show when the remote or
  the configurator chooses them, or when the default is cleared and the
  resting panes take turns.

## Alternatives considered

- **Home Assistant pushes its states to pub** (a `rest_command` or an
  automation writing JSON through pub-signals). This keeps pub credential-free,
  but needs a write path into the share from Home Assistant and an automation
  per change. Chris chose the pull.
- **The Home pane without presence or the alarm.** Rejected by the household
  ("everything").
- **Agent PRs from the queue's logs**: PR URLs scraped from `logs/*.txt`. The
  search API answers in one call, shows a PR's current state, and keeps the
  producer out of the job logs.
- **A Home Assistant user's own token, not a dedicated user.** It works, but
  revoking it would sign out a person, and the token's actions would carry
  their name in Home Assistant's logbook.
