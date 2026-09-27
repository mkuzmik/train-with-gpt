"""Unit tests for scripts/release_version.py (run by the Release workflow).

Pure version logic directly; the CLI against a real temp git repo, with PR
labels supplied through --labels-json instead of the GitHub API.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import git

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_version.py"

sys.path.insert(0, str(SCRIPT.parent))
try:
    import release_version as rv
finally:
    sys.path.remove(str(SCRIPT.parent))


# --- pure logic ------------------------------------------------------------------

@pytest.mark.parametrize("tag, expected", [
    ("v0.1.0", (0, 1, 0)), ("v10.20.30", (10, 20, 30)),
    ("0.1.0", None), ("v1.2", None), ("v01.2.3", None), ("v1.2.3-rc.1", None), ("v1.2.3.4", None), ("latest", None),
])
def test_parse_tag(tag, expected):
    assert rv.parse_tag(tag) == expected


def test_latest_version_compares_numerically_and_ignores_other_tags():
    assert rv.latest_version(["v0.9.0", "v0.10.0", "v0.2.5", "nightly", "v1.0.0-rc.1"]) == (0, 10, 0)
    assert rv.latest_version(["nightly"]) is None
    assert rv.latest_version([]) is None


@pytest.mark.parametrize("label_sets, force, expected", [
    ([None], False, "patch"),                                         # direct push
    ([[]], False, "patch"),                                           # unlabelled PR
    ([["enhancement"]], False, "patch"),
    ([["release:minor"]], False, "minor"),
    ([["release:patch"], ["release:major"], []], False, "major"),     # largest wins
    ([["release:skip"]], False, None),
    ([["skip-release", "release:major"]], False, None),               # skip wins over a bump
    ([["release:skip"], ["release:minor"]], False, "minor"),          # skipped PR ignored
    ([["release:skip"]], True, "patch"),                              # manual run always releases
    ([], False, None),
])
def test_bump_for(label_sets, force, expected):
    assert rv.bump_for(label_sets, force=force) == expected


@pytest.mark.parametrize("latest, bump, expected", [
    (None, "patch", (0, 1, 0)), (None, "major", (0, 1, 0)),
    ((0, 1, 0), "patch", (0, 1, 1)), ((0, 1, 7), "minor", (0, 2, 0)), ((0, 9, 3), "major", (1, 0, 0)),
])
def test_next_version(latest, bump, expected):
    assert rv.next_version(latest, bump) == expected


# --- CLI against a real repo -------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "--quiet", "-b", "main")
    return path


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "--quiet", "-m", name)
    return git(repo, "rev-parse", "HEAD").strip()


def run(repo: Path, labels: dict, *args: str, output: Path = None, releases: dict = None):
    labels_file = repo.parent / "labels.json"
    labels_file.write_text(json.dumps(labels))
    if releases is None:  # by default every tag is a release this workflow published
        releases = {tag: "github-actions[bot]" for tag in git(repo, "tag", "--list").split()}
    releases_file = repo.parent / "releases.json"
    releases_file.write_text(json.dumps(releases))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    if output:
        env["GITHUB_OUTPUT"] = str(output)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--labels-json", str(labels_file), "--releases-json", str(releases_file), *args],
        cwd=repo, env=env, capture_output=True, text=True, timeout=30,
    )


def test_first_release_is_v0_1_0(repo, tmp_path):
    commit(repo, "a")
    head = commit(repo, "b")
    out = tmp_path / "gh_output"

    result = run(repo, {head: ["release:major"]}, output=out)

    assert result.returncode == 0, result.stderr
    assert "release=true version=v0.1.0" in result.stdout
    assert out.read_text().splitlines()[:2] == ["release=true", "version=v0.1.0"]


def test_first_release_skipped_when_head_pr_is_skip(repo):
    head = commit(repo, "a")

    result = run(repo, {head: ["release:skip"]})

    assert "release=false" in result.stdout


def test_bump_uses_largest_label_since_latest_tag(repo):
    commit(repo, "a")
    git(repo, "tag", "v0.3.2")
    first = commit(repo, "b")
    second = commit(repo, "c")

    result = run(repo, {first: ["release:minor"], second: None})

    assert "release=true version=v0.4.0" in result.stdout
    assert "minor bump from v0.3.2 (2 change(s))" in result.stdout


def test_changes_before_latest_tag_are_ignored(repo):
    old = commit(repo, "a")
    git(repo, "tag", "v1.0.0")
    head = commit(repo, "b")

    result = run(repo, {old: ["release:major"], head: []})

    assert "version=v1.0.1" in result.stdout


def test_all_skipped_changes_release_nothing(repo):
    commit(repo, "a")
    git(repo, "tag", "v0.1.0")
    head = commit(repo, "b")

    result = run(repo, {head: ["skip-release"]})

    assert "release=false" in result.stdout


def test_head_released_by_this_workflow_is_a_no_op(repo, tmp_path):
    commit(repo, "a")
    git(repo, "tag", "v0.1.0")
    out = tmp_path / "gh_output"

    result = run(repo, {}, output=out, releases={"v0.1.0": "github-actions[bot]"})

    assert result.returncode == 0
    assert "release=false version=v0.1.0" in result.stdout
    assert "already released as v0.1.0" in result.stdout
    assert out.read_text().startswith("release=false\n")


@pytest.mark.parametrize("bump, expected", [("force", "v0.1.1"), ("minor", "v0.2.0"), ("major", "v1.0.0")])
def test_manual_run_always_releases(repo, bump, expected):
    commit(repo, "a")
    git(repo, "tag", "v0.1.0")
    head = commit(repo, "b")

    result = run(repo, {head: ["release:skip"]}, "--bump", bump)

    assert f"release=true version={expected}" in result.stdout


def test_tags_not_reachable_from_head_are_ignored(repo):
    commit(repo, "a")
    git(repo, "tag", "v0.1.0")
    git(repo, "switch", "--quiet", "-c", "side")
    commit(repo, "side")
    git(repo, "tag", "v5.0.0")
    git(repo, "switch", "--quiet", "main")
    head = commit(repo, "b")

    result = run(repo, {head: []})

    assert "version=v0.1.1" in result.stdout


@pytest.mark.parametrize("author, made_by", [(None, "with no GitHub Release"), ("someone", "published by someone")])
def test_head_tagged_outside_the_workflow_is_an_error(repo, tmp_path, author, made_by):
    """E.g. "Draft a new release" on main's head: never tested, so don't treat it as released."""
    commit(repo, "a")
    git(repo, "tag", "v0.2.0")
    out = tmp_path / "gh_output"

    result = run(repo, {}, output=out, releases={"v0.2.0": author})

    assert result.returncode == 1
    assert f"is tagged v0.2.0 {made_by}, not by this workflow" in result.stderr
    assert "Delete the release and the tag v0.2.0" in result.stderr
    assert not out.exists()


def test_first_release_counts_earlier_unreleased_changes(repo):
    """No tag yet, an unlabelled PR whose run was superseded, then a release:skip PR."""
    earlier = commit(repo, "a")
    head = commit(repo, "b")

    result = run(repo, {earlier: [], head: ["release:skip"]})

    assert result.returncode == 0, result.stderr
    assert "release=true version=v0.1.0 (first release)" in result.stdout


def test_any_hand_made_tag_on_head_is_an_error(repo):
    """A workflow release on the head doesn't excuse a second, hand-made tag there."""
    commit(repo, "a")
    git(repo, "tag", "v0.2.0")
    git(repo, "tag", "v0.1.9")

    result = run(repo, {}, releases={"v0.2.0": "github-actions[bot]", "v0.1.9": None})

    assert result.returncode == 1
    assert "is tagged v0.1.9 with no GitHub Release, not by this workflow" in result.stderr


def test_hand_made_baseline_tag_is_an_error(repo, tmp_path):
    """A hand-made tag on an older main commit must not become the version baseline."""
    commit(repo, "a")
    git(repo, "tag", "v0.1.0")
    commit(repo, "b")
    git(repo, "tag", "v0.5.0")
    head = commit(repo, "c")
    out = tmp_path / "gh_output"

    result = run(repo, {head: []}, output=out, releases={"v0.1.0": "github-actions[bot]", "v0.5.0": "someone"})

    assert result.returncode == 1
    assert "is tagged v0.5.0 published by someone, not by this workflow" in result.stderr
    assert not out.exists()


def test_first_release_skipped_when_every_change_is_skipped(repo):
    first = commit(repo, "a")
    head = commit(repo, "b")

    result = run(repo, {first: ["skip-release"], head: ["release:skip"]})

    assert "release=false" in result.stdout
