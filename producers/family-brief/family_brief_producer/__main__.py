"""Entry point: ``python3 -m family_brief_producer --webroot /srv/www``."""

import argparse
import logging
import sys
import time

from .document import parse_ts
from .producer import DEFAULT_SOURCE, DEFAULT_TZ, Producer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="family_brief_producer",
        description="Keep the family today-and-tomorrow pane on the bus while the brief is fresh.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="the Family Brief document (http:// or file://; default %(default)s)")
    parser.add_argument("--tz", default=DEFAULT_TZ,
                        help="the household's time zone, for what today means (default %(default)s)")
    parser.add_argument("--interval", type=float, default=60.0,
                        help="seconds between cycles (default 60)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--now", type=parse_ts, default=None, metavar="RFC3339",
                        help="pretend the clock reads this (to render a fixture for its own day)")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    clock = (lambda: args.now) if args.now else None
    producer = Producer(args.webroot, args.source, args.tz, clock=clock)
    while True:
        try:
            producer.cycle()
        except Exception:  # keep the loop alive; the journal gets the trace
            logging.exception("cycle failed")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
