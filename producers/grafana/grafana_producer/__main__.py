"""Entry point: ``python3 -m grafana_producer --webroot /srv/www --grafana-url URL --slots FILE``.

The token file defaults to ``$CREDENTIALS_DIRECTORY/grafana-token``, where
systemd puts the unit's ``LoadCredential=grafana-token:...`` (kalmia's
brasenia-grafana unit).
"""

import argparse
import logging
import os
import sys
import time
import urllib.parse
from datetime import datetime

from .producer import DEFAULT_TZ, Producer
from .slots import SlotError, load


def parse_ts(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("%r has no UTC offset" % value)
    return when


def stack_url(value):
    """argparse type: an https URL with no user, password, query or fragment."""
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise argparse.ArgumentTypeError(
            "%r is not a plain https:// stack URL (no credentials in it)" % value)
    return value.rstrip("/")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="grafana_producer",
        description="Keep Grafana dashboards on the bus as panes, rendered by the stack's render API.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--grafana-url", required=True, type=stack_url,
                        help="the Grafana Cloud stack, e.g. https://<stack>.grafana.net")
    parser.add_argument("--slots", required=True, metavar="FILE",
                        help="the slot file (JSON; see README)")
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    parser.add_argument("--token-file",
                        default=os.path.join(credentials, "grafana-token") if credentials else None,
                        help="file holding a Viewer service-account token "
                             "(default $CREDENTIALS_DIRECTORY/grafana-token under systemd)")
    parser.add_argument("--tz", default=DEFAULT_TZ,
                        help="the household's time zone (default %(default)s)")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="seconds between checks for a due slot (default 30)")
    parser.add_argument("--once", action="store_true",
                        help="render every slot once and exit")
    parser.add_argument("--now", type=parse_ts, default=None, metavar="RFC3339",
                        help="pretend the clock reads this")
    args = parser.parse_args(argv)
    if not args.token_file:
        parser.error("--token-file is required outside systemd (no $CREDENTIALS_DIRECTORY)")
    try:
        slots = load(args.slots)
    except SlotError as err:
        parser.error(str(err))

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    clock = (lambda: args.now) if args.now else None
    producer = Producer(args.webroot, args.token_file, args.grafana_url, slots, args.tz,
                        clock=clock)
    while True:
        failed = False
        try:
            failed = producer.cycle() > 0
        except Exception as err:  # keep the loop alive; no trace or message, which could carry the token
            logging.error("cycle failed (%s)", type(err).__name__)
            failed = True
        if args.once:
            return 1 if failed else 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
