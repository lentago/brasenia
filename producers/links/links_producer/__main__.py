"""Entry point: ``python3 -m links_producer --webroot /srv/www``."""

import argparse
import logging
import sys
import time

from .producer import Producer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="links_producer",
        description="Keep a link pane on the bus for each standing slot (#97).",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="seconds between cycles (default 30)")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(levelname)s %(message)s")
    producer = Producer(args.webroot)
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
