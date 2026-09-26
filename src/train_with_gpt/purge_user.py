"""Operator CLI: remove one hosted-server user's stored data from store.db.

    train-with-gpt-purge-user <strava_athlete_id>

For someone who signed in before the allowlist existed, or was taken off it.
Taking a user off ALLOWED_STRAVA_ATHLETE_IDS already locks them out; this
also deletes what the store still holds for them (store.purge_user): Strava
tokens and name, intervals.icu connection, our tokens and codes. Before
deleting, it asks Strava to revoke this app's access (best effort, with the
stored access token; if that token has expired, the athlete can still revoke
it under Strava -> Settings -> My Apps).

Notes and goals in the training repo (notes/<id>/, goals/<id>.md) are left
alone; remove them there by hand if needed.
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

from . import store
from .strava_client import deauthorize

ROOT_HINT = """\
Run this as the `app` user, not root: files root creates next to store.db
break the server. Inside the container:

    su app -c 'train-with-gpt-purge-user <id>'
"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="train-with-gpt-purge-user",
        description=(
            "Delete one user's stored Strava tokens/name, intervals.icu key and "
            "our access tokens from store.db."
        ),
    )
    parser.add_argument("user_id", help="the user's Strava athlete id")
    parser.add_argument(
        "--no-deauthorize",
        action="store_true",
        help="don't ask Strava to revoke this app's access before deleting",
    )
    args = parser.parse_args(argv)
    if not args.user_id.isascii() or not args.user_id.isdigit():
        parser.error("user_id must be a Strava athlete id (digits only)")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(ROOT_HINT, file=sys.stderr)
        return 2

    store.init_db()
    user = store.get_user(args.user_id)
    if user and not args.no_deauthorize:
        revoked = asyncio.run(deauthorize(user["access_token"]))
        print(f"Strava access revoked: {'yes' if revoked else 'no (revoke it on Strava instead)'}")

    deleted = store.purge_user(args.user_id)
    for table, count in deleted.items():
        print(f"{table}: {count} row(s) deleted")
    print(f"Not touched: notes/{args.user_id}/ and goals/{args.user_id}.md in the training repo.")
    return 0


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
