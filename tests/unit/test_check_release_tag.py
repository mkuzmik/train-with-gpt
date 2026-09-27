"""Unit tests for scripts/check_release_tag.py (run by the release workflow)."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_release_tag.py"

PYPROJECT = """\
[build-system]
requires = ["hatchling"]
version = "9.9.9"

[project]
name = "demo"
# the one that counts
version = "1.4.0"  # bump with uv lock
dependencies = []

[tool.other]
version = "0.0.1"
"""


def run(tag: str, pyproject: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag, "--pyproject", str(pyproject)],
        capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def pyproject(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT)
    return path


def test_matching_tag_passes(pyproject):
    result = run("v1.4.0", pyproject)

    assert result.returncode == 0, result.stderr
    assert "v1.4.0 matches pyproject.toml" in result.stdout


@pytest.mark.parametrize("tag", ["v1.4.1", "v9.9.9", "v0.0.1"])
def test_tag_for_another_version_fails(pyproject, tag):
    result = run(tag, pyproject)

    assert result.returncode == 1
    assert "does not match pyproject.toml version '1.4.0'" in result.stderr


@pytest.mark.parametrize(
    "tag", ["1.4.0", "v1.4", "v01.4.0", "release-1.4.0", "v1.4.0.0", "v1.4.0-rc.1", "v1.4.0rc1", "v1.4.0 "]
)
def test_non_semver_tag_fails(pyproject, tag):
    result = run(tag, pyproject)

    assert result.returncode == 1
    assert "is not a SemVer release tag" in result.stderr


def test_missing_project_version_fails(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\n\n[tool.x]\nversion = "1.0.0"\n')

    result = run("v1.0.0", path)

    assert result.returncode == 1
    assert "no [project] version" in result.stderr


def test_repo_pyproject_has_a_releasable_version():
    """The real pyproject.toml parses, and v<version> is a valid tag for it."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import check_release_tag
    finally:
        sys.path.remove(str(SCRIPT.parent))
    text = (ROOT / "pyproject.toml").read_text()

    version = check_release_tag.project_version(text)

    assert check_release_tag.check(f"v{version}", text) == ""
