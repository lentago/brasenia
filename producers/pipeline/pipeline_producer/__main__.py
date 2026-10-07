"""Entry point: ``python3 -m pipeline_producer --webroot /srv/www --url-base http://pub.lan``."""

import argparse
import logging
import sys
import time

from .document import parse_ts
from .producer import Producer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pipeline_producer",
        description="Render the change-pipeline pane while a change is in flight.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at --url-base (holds viewport/)")
    parser.add_argument("--url-base", default="http://pub.lan",
                        help="where viewport/pipeline.json is read from (http:// or file://)")
    parser.add_argument("--interval", type=float, default=15.0,
                        help="seconds between cycles (default 15)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--now", type=parse_ts, default=None, metavar="RFC3339",
                        help="pretend the clock reads this (to render a fixture whose generated_at has passed)")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    clock = (lambda: args.now) if args.now else None
    producer = Producer(args.webroot, args.url_base, clock=clock)
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
