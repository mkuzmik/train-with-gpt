"""Which Strava athletes may sign in to the hosted (HTTP/OAuth) server.

A privacy stopgap: until the privacy policy and the Strava API policy work
are sorted out, the hosted server only processes data for athletes an
operator listed explicitly. Configured through one env var (a `fly secret` in
production, never committed):

    ALLOWED_STRAVA_ATHLETE_IDS="111, 222"

It fails closed: unset or empty means nobody can sign in, and there is no
wildcard. Invalid entries stop the server at startup rather than being
silently skipped. Ids are never logged, only how many there are.

Only the HTTP entrypoint uses this. The personal stdio server (one
intervals.icu API key, no sign-in) is unaffected.
"""

import os
import sys
from typing import Mapping, Optional

ENV_VAR = "ALLOWED_STRAVA_ATHLETE_IDS"


class AllowlistError(ValueError):
    """ALLOWED_STRAVA_ATHLETE_IDS is set but malformed."""


def parse_allowlist(raw: Optional[str]) -> frozenset[str]:
    """Parse a comma-separated list of Strava athlete ids.

    Whitespace around entries and empty entries (e.g. a trailing comma) are
    ignored. Anything that isn't a positive integer raises AllowlistError;
    the message doesn't echo the entry, since a typo in an id is still an id.
    Ids are returned as canonical decimal strings, the same form as a user id
    (`str(athlete["id"])`) and an access token's `subject`.
    """
    ids = set()
    for position, entry in enumerate((raw or "").split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        if not entry.isascii() or not entry.isdigit() or int(entry) == 0:
            hint = " (there is no wildcard: list every athlete id)" if entry == "*" else ""
            raise AllowlistError(
                f"{ENV_VAR}: entry #{position} is not a Strava athlete id "
                f"(expected comma-separated positive integers){hint}"
            )
        ids.add(str(int(entry)))
    return frozenset(ids)


def load_allowlist(environ: Optional[Mapping[str, str]] = None) -> frozenset[str]:
    """Read and parse ALLOWED_STRAVA_ATHLETE_IDS, logging only how many ids it has."""
    environ = os.environ if environ is None else environ
    allowed = parse_allowlist(environ.get(ENV_VAR))
    if allowed:
        print(f"[Allowlist] {len(allowed)} Strava athlete(s) allowed to sign in", file=sys.stderr)
    else:
        print(
            f"[Allowlist] WARNING: {ENV_VAR} is not set or empty - nobody can sign in "
            "to this server. Set it to a comma-separated list of Strava athlete ids.",
            file=sys.stderr,
        )
    return allowed
