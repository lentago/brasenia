"""Entry point: ``python3 -m prs_producer --webroot /srv/www``.

The token file defaults to ``$CREDENTIALS_DIRECTORY/github-token``, where
systemd puts the unit's ``LoadCredential=github-token:...`` (kalmia's
brasenia-prs unit, ADR-0021). Without a token the producer reads anonymously.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

from . import github
from .producer import DEFAULT_TZ, Producer


def parse_ts(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("%r has no UTC offset" % value)
    return when


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="prs_producer",
        description="Keep the PRs pane on the bus from GitHub's search and GraphQL APIs.",
    )
    parser.add_argument("--webroot", required=True,
                        help="directory served at http://pub.lan (holds viewport/)")
    parser.add_argument("--scope", default=github.DEFAULT_SCOPE,
                        help="search qualifier naming the repos (default %(default)s)")
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    parser.add_argument("--token-file",
                        default=os.path.join(credentials, "github-token") if credentials else None,
                        help="file holding a public-read-only GitHub token "
                             "(default $CREDENTIALS_DIRECTORY/github-token under systemd; "
                             "without one, reads are anonymous)")
    parser.add_argument("--tz", default=DEFAULT_TZ,
                        help="the household's time zone, for clock times and \"today\" (default %(default)s)")
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
    # systemd copies the credential when the unit starts, so it is read once.
    token = github.read_token(args.token_file)
    if token is None:
        logging.warning("no GitHub token at %s; reading anonymously, without PR state",
                        args.token_file or "(no --token-file)")
    producer = Producer(args.webroot, args.tz, args.scope, client=github.Client(token), clock=clock)
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
