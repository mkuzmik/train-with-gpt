"""Small helpers shared by unit and integration tests (no fixtures here)."""

import subprocess
import tempfile
from pathlib import Path

# Fake credentials the fixtures configure; never real ones.
STRAVA_CLIENT_ID = "test-strava-client-id"
STRAVA_CLIENT_SECRET = "test-strava-client-secret"
INTERVALS_API_KEY = "test-intervals-key"


def git(cwd: Path, *args: str) -> str:
    """Run a git command in `cwd` and return its stdout (raises on failure)."""
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def make_bare_remote(path: Path) -> Path:
    """Create a bare repo on branch `main` with one initial commit (a README)."""
    path.mkdir(parents=True)
    git(path, "init", "--bare", "--quiet")
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")

    seed = path.parent / f"{path.name}-seed"
    seed.mkdir()
    git(seed, "init", "--quiet")
    git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
    git(seed, "remote", "add", "origin", str(path))
    (seed / "README.md").write_text("Training context\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "--quiet", "-m", "Initial commit")
    git(seed, "push", "--quiet", "origin", "HEAD:main")
    return path


def clone(remote: Path, dest: Path) -> Path:
    """Clone `remote` into `dest`; the clone's `main` tracks origin/main."""
    subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(dest)],
        check=True, capture_output=True, text=True,
    )
    return dest


def push_files(remote: Path, files: dict[str, str], message: str = "Add files") -> None:
    """Commit `files` ({relative path: content}) to `remote` from a separate clone,
    as if another device/deployment had pushed them."""
    workdir = Path(tempfile.mkdtemp(prefix="other-clone-", dir=remote.parent))
    other = clone(remote, workdir / "repo")
    for relative, content in files.items():
        target = other / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(other, "add", relative)
    git(other, "commit", "--quiet", "-m", message)
    git(other, "push", "--quiet", "origin", "HEAD:main")


def remote_files(remote: Path, ref: str = "main") -> list[str]:
    """Paths of all files committed on `ref` in a (bare) repo."""
    return git(remote, "ls-tree", "-r", "--name-only", ref).split()


def remote_file(remote: Path, path: str, ref: str = "main") -> str:
    """Contents of `path` as committed on `ref` in a (bare) repo."""
    return git(remote, "show", f"{ref}:{path}")


def text_of(result) -> str:
    """The single TextContent's text from a tool handler's result."""
    assert len(result) == 1, result
    return result[0].text
