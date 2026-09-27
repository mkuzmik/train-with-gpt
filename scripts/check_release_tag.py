#!/usr/bin/env python3
"""Check that a release tag matches the version in pyproject.toml.

    python scripts/check_release_tag.py v1.2.3 [--pyproject path/to/pyproject.toml]

Tags are SemVer with a leading "v" (vX.Y.Z), and
pyproject.toml's [project] version is the single source of truth: the tag
must be exactly "v" + that version. Exits 0 on a match, 1 otherwise. Used by
.github/workflows/release.yml before a GitHub Release is created.

Standard library only, and no tomllib (Python 3.11+): CI also runs 3.10.
"""

import argparse
import re
import sys
from pathlib import Path

# Plain SemVer MAJOR.MINOR.PATCH with a "v" prefix. Pre-releases aren't
# supported: SemVer ("1.0.0-rc.1") and PEP 440 ("1.0.0rc1", what Python
# packaging normalises pyproject's version to) spell them differently.
TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_TABLE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")
_VERSION = re.compile(r"""^\s*version\s*=\s*(["'])([^"']*)\1\s*(?:#.*)?$""")


def project_version(pyproject_text: str) -> str:
    """The `version` key of the [project] table."""
    table = None
    for line in pyproject_text.splitlines():
        header = _TABLE.match(line)
        if header:
            table = header.group(1)
            continue
        if table == "project":
            match = _VERSION.match(line)
            if match:
                return match.group(2)
    raise ValueError("no [project] version in pyproject.toml")


def check(tag: str, pyproject_text: str) -> str:
    """Return an error message, or "" if `tag` is a valid release tag for this version."""
    if not TAG.match(tag):
        return f"tag {tag!r} is not a SemVer release tag (vX.Y.Z)"
    try:
        version = project_version(pyproject_text)
    except ValueError as e:
        return str(e)
    if tag != f"v{version}":
        return f"tag {tag!r} does not match pyproject.toml version {version!r} (expected 'v{version}')"
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="release tag, e.g. v1.2.3")
    parser.add_argument("--pyproject", default="pyproject.toml", type=Path)
    args = parser.parse_args(argv)

    error = check(args.tag, args.pyproject.read_text(encoding="utf-8"))
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{args.tag} matches pyproject.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
