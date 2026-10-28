"""Entry point: ``python3 -m focus_producer --webroot /srv/www``."""

import argparse
import logging
import sys
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .github import GitHub
from .producer import Producer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="focus_producer",
        description="Render an open-PRs pane for every repo with a fresh session beacon.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at --url-base (holds viewport/)")
    parser.add_argument("--url-base", default="http://pub.lan",
                        help="where the webroot is served; pipeline.json is read from here")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="seconds between cycles (default 30)")
    parser.add_argument("--tz", default="America/New_York",
                        help="time zone for the clock times on panes (default America/New_York)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    args = parser.parse_args(argv)
    try:
        tz = ZoneInfo(args.tz)
    except (ZoneInfoNotFoundError, ValueError):
        parser.error("--tz %r is not a known time zone" % args.tz)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    producer = Producer(args.webroot, args.url_base, GitHub(), tz=tz)
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
