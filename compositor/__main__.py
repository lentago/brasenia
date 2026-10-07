import argparse
import sys
import time
from datetime import datetime, timezone

from . import bus


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m compositor",
        description="Rank the viewport pane bus by rubric v1 and publish "
                    "<webroot>/viewport/current.json.")
    parser.add_argument("--webroot", required=True,
                        help="web root that holds viewport/ and brief/ "
                             "(on pub: /srv/www)")
    parser.add_argument("--url-base", default="http://pub.lan",
                        help="URL the web root is served at "
                             "(default: %(default)s)")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="seconds between evaluations "
                             "(default: %(default)s)")
    parser.add_argument("--once", action="store_true",
                        help="evaluate once and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")

    def log(line):
        print(line, flush=True)

    state = bus.load_state(bus.paths(args.webroot)["state"])
    try:
        while True:
            state = bus.tick(args.webroot, args.url_base, state,
                             datetime.now(timezone.utc), log)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
