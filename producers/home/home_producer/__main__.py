"""Entry point: ``python3 -m home_producer --webroot /srv/www``.

The token file defaults to ``$CREDENTIALS_DIRECTORY/ha-token``, where systemd
puts the unit's ``LoadCredential=ha-token:...`` (kalmia's brasenia-home unit).
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

from .producer import DEFAULT_TZ, DEFAULT_URL, Producer


def parse_ts(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("%r has no UTC offset" % value)
    return when


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="home_producer",
        description="Keep the home and weather panes on the bus from Home Assistant's states.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--ha-url", default=DEFAULT_URL,
                        help="Home Assistant's base URL (default %(default)s)")
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    parser.add_argument("--token-file",
                        default=os.path.join(credentials, "ha-token") if credentials else None,
                        help="file holding a long-lived access token "
                             "(default $CREDENTIALS_DIRECTORY/ha-token under systemd)")
    parser.add_argument("--weather", default=None, metavar="ENTITY_ID",
                        help="the weather entity (default: the first weather.* by id)")
    parser.add_argument("--hide", action="append", default=[], metavar="ENTITY_ID",
                        help="leave this entity off the home pane (repeatable)")
    parser.add_argument("--tz", default=DEFAULT_TZ,
                        help="the household's time zone (default %(default)s)")
    parser.add_argument("--interval", type=float, default=60.0,
                        help="seconds between cycles (default 60)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--now", type=parse_ts, default=None, metavar="RFC3339",
                        help="pretend the clock reads this")
    args = parser.parse_args(argv)
    if not args.token_file:
        parser.error("--token-file is required outside systemd (no $CREDENTIALS_DIRECTORY)")

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    clock = (lambda: args.now) if args.now else None
    producer = Producer(args.webroot, args.token_file, args.ha_url, args.weather, args.hide,
                        args.tz, clock=clock)
    while True:
        failed = False
        try:
            producer.cycle()
        except Exception:  # keep the loop alive; the journal gets the trace
            logging.exception("cycle failed")
            failed = True
        if args.once:
            return 1 if failed else 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
