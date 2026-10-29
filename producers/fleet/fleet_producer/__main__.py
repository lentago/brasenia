"""Entry point: ``python3 -m fleet_producer --webroot /srv/www --jobs /srv/claude-jobs``."""

import argparse
import logging
import sys
import time
from datetime import datetime

from .producer import DEFAULT_JOBS, DEFAULT_TZ, Producer


def parse_ts(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("%r has no UTC offset" % value)
    return when


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fleet_producer",
        description="Keep the fleet pane on the bus from the claytonia job queue.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--jobs", default=DEFAULT_JOBS,
                        help="the claude-jobs queue, mounted read-only (default %(default)s)")
    parser.add_argument("--tz", default=DEFAULT_TZ,
                        help="the household's time zone (default %(default)s)")
    parser.add_argument("--interval", type=float, default=60.0,
                        help="seconds between cycles (default 60)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--now", type=parse_ts, default=None, metavar="RFC3339",
                        help="pretend the clock reads this")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    clock = (lambda: args.now) if args.now else None
    producer = Producer(args.webroot, args.jobs, args.tz, clock=clock)
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
