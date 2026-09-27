#!/usr/bin/env python3
"""Plan the next release: which vX.Y.Z tag (if any) the commit being released gets.

    python scripts/release_version.py --head <sha> [--bump auto|patch|minor|major]
                                      [--repo owner/name] [--labels-json FILE]

Git tags are the source of truth for the version (pyproject.toml's is a
placeholder). The next version is the highest vX.Y.Z tag, bumped by the
labels of the pull requests merged since that tag:

- `release:major` / `release:minor` / `release:patch`: that bump (default:
  patch). The largest one across the unreleased PRs wins.
- `release:skip` or `skip-release`: this PR alone doesn't cause a release.
  If every unreleased change is skipped, nothing is released; its changes
  go out with the next release.
- A direct push (no PR) counts as a patch.
- No tags yet: the first release is v0.1.0 (unless every change since the
  root is skipped).
- The head commit already has a vX.Y.Z tag whose GitHub Release this
  workflow published: nothing to do (re-runs are idempotent). A tag made any
  other way (e.g. "Draft a new release") is an error: it was never tested.

The manual "Run workflow" path always releases: `--bump force` uses the
labels but at least a patch, and an explicit `--bump patch|minor|major` uses
that bump.

Prints the plan and, under GitHub Actions, writes `release=true|false`,
`version=vX.Y.Z` and `reason=...` to $GITHUB_OUTPUT. PR labels come from the
GitHub API through `gh` (`repos/<repo>/commits/<sha>/pulls`), or from
`--labels-json` ({"<sha>": ["label", ...] | null}; null = no PR) in tests;
release authors likewise from `repos/<repo>/releases/tags/<tag>`, or
`--releases-json` ({"<tag>": "<login>" | null}).

Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
FIRST_VERSION = (0, 1, 0)
BUMPS = ("patch", "minor", "major")
SKIP_LABELS = frozenset({"release:skip", "skip-release"})
BUMP_LABELS = {"release:patch": "patch", "release:minor": "minor", "release:major": "major"}
# Who publishes releases in the Release workflow (GITHUB_TOKEN).
RELEASE_BOT = "github-actions[bot]"

Version = tuple[int, int, int]


def parse_tag(tag: str) -> Optional[Version]:
    match = TAG.match(tag.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def format_version(version: Version) -> str:
    return "v{}.{}.{}".format(*version)


def latest_version(tags: Iterable[str]) -> Optional[Version]:
    """The highest vX.Y.Z tag (by version, not by date); other tags are ignored."""
    versions = [v for v in (parse_tag(t) for t in tags) if v is not None]
    return max(versions) if versions else None


def bump_for(label_sets: Iterable[Optional[Iterable[str]]], force: bool = False) -> Optional[str]:
    """The bump for a set of unreleased changes, or None when there's nothing to release.

    One entry per change: the PR's labels, or None for a direct push.
    """
    kinds = []
    for labels in label_sets:
        labels = set(labels or ())
        if labels & SKIP_LABELS:
            continue
        kinds.append(max((BUMP_LABELS[l] for l in labels if l in BUMP_LABELS), key=BUMPS.index, default="patch"))
    if not kinds:
        return "patch" if force else None
    return max(kinds, key=BUMPS.index)


def next_version(latest: Optional[Version], bump: str) -> Version:
    if latest is None:
        return FIRST_VERSION
    major, minor, patch = latest
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


# --- git / GitHub ------------------------------------------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _pr_labels(repo: str, sha: str) -> Optional[list[str]]:
    """Labels of the merged PR that produced `sha`, or None for a direct push."""
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{sha}/pulls"], check=True, capture_output=True, text=True
    ).stdout
    merged = [pr for pr in json.loads(out) if pr.get("merged_at")]
    exact = [pr for pr in merged if pr.get("merge_commit_sha") == sha]
    chosen = (exact or merged or [None])[0]
    return None if chosen is None else [label["name"] for label in chosen.get("labels", [])]


class ReleaseError(Exception):
    """The repo is in a state the workflow must not paper over."""


def _release_author(repo: str, tag: str) -> Optional[str]:
    """Login of whoever published the GitHub Release for `tag`, or None if there is none."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/tags/{tag}", "--jq", ".author.login"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        if "404" in result.stderr or "Not Found" in result.stderr:
            return None
        raise ReleaseError(f"could not look up the release for {tag}: {result.stderr.strip()}")
    return result.stdout.strip() or None


def _until_first_unskipped(label_sets):
    """Yield label sets up to and including the first one that isn't skipped."""
    for labels in label_sets:
        yield labels
        if not (set(labels or ()) & SKIP_LABELS):
            return


def plan(head: str, bump: str, repo: Optional[str], labels_json: Optional[dict] = None,
         releases_json: Optional[dict] = None) -> dict:
    head = _git("rev-parse", head).strip()

    def require_workflow_release(tag: str) -> None:
        """Only tags this workflow released count; e.g. "Draft a new release" skipped the tests."""
        author = releases_json.get(tag) if releases_json is not None else _release_author(repo, tag)
        if author != RELEASE_BOT:
            made_by = f"published by {author}" if author else "with no GitHub Release"
            where = _git("rev-parse", "--short", f"{tag}^{{commit}}").strip()
            raise ReleaseError(
                f"{where} is tagged {tag} {made_by}, not by this workflow, so it was never tested. "
                f"Delete the release and the tag {tag}, then re-run this workflow."
            )

    on_head = [t for t in _git("tag", "--points-at", head).split() if parse_tag(t)]
    if on_head:
        tag = max(on_head, key=parse_tag)
        require_workflow_release(tag)
        return {"release": False, "version": tag, "reason": f"{head[:7]} is already released as {tag}"}

    tags = [t for t in _git("tag", "--list", "v*", "--merged", head).split() if parse_tag(t)]
    latest = latest_version(tags)
    if latest is not None:
        # The baseline must be a real release too, or it would skip everything before it.
        require_workflow_release(format_version(latest))
    since = f"{format_version(latest)}..{head}" if latest else head
    commits = _git("rev-list", "--first-parent", since).split()

    def labels(sha):
        if labels_json is not None:
            return labels_json.get(sha)
        return _pr_labels(repo, sha)

    if bump in ("auto", "force"):
        label_sets = (labels(sha) for sha in commits)
        if latest is None:
            # The first release is v0.1.0 whatever the labels, so it only needs
            # one unreleased change that isn't skipped (usually the head's own).
            label_sets = _until_first_unskipped(label_sets)
        kind = bump_for(label_sets, force=(bump == "force"))
    else:
        kind = bump
    if kind is None:
        return {"release": False, "version": "", "reason": "every unreleased change is labelled release:skip"}
    version = format_version(next_version(latest, kind))
    if latest is None:
        return {"release": True, "version": version, "reason": "first release"}
    return {"release": True, "version": version,
            "reason": f"{kind} bump from {format_version(latest)} ({len(commits)} change(s))"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--head", default="HEAD", help="commit to release (default: HEAD)")
    parser.add_argument("--bump", default="auto", choices=("auto", "force", *BUMPS),
                        help="auto: from PR labels; force: from labels but at least a patch; or an explicit bump")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name, for PR labels")
    parser.add_argument("--labels-json", type=Path, help="test override: {sha: [labels] | null}")
    parser.add_argument("--releases-json", type=Path, help="test override: {tag: release author login | null}")
    args = parser.parse_args(argv)

    labels_json = json.loads(args.labels_json.read_text()) if args.labels_json else None
    releases_json = json.loads(args.releases_json.read_text()) if args.releases_json else None
    if (labels_json is None or releases_json is None) and not args.repo:
        parser.error("--repo (or GITHUB_REPOSITORY) is needed to look up PR labels and releases")

    try:
        result = plan(args.head, args.bump, args.repo, labels_json, releases_json)
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"release={'true' if result['release'] else 'false'} version={result['version']} ({result['reason']})")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"release={'true' if result['release'] else 'false'}\n")
            fh.write(f"version={result['version']}\n")
            fh.write(f"reason={result['reason']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
