"""Small helpers shared by unit and integration tests (no fixtures here)."""

import contextlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

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


def race_on_commit(repo: Path, remote: Path, files: dict[str, str], times: int = 1) -> None:
    """Make another writer push `files` to `remote` right after each of the next
    `times` commits in `repo` - i.e. between our commit and our push, so our
    push is rejected. Deterministic: a real git post-commit hook in `repo`.
    Each run appends its run number to the contents, so every push is a change."""
    counter = repo / ".git" / "race-count"
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"""#!{sys.executable}
import os, sys
from pathlib import Path
for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX"):
    os.environ.pop(name, None)
sys.path.insert(0, {str(_PROJECT_ROOT)!r})
from tests.support import push_files

counter = Path({str(counter)!r})
run = int(counter.read_text()) if counter.exists() else 0
if run < {times}:
    counter.write_text(str(run + 1))
    files = {files!r}
    push_files(Path({str(remote)!r}), {{p: f"{{c}}(concurrent push {{run}})\\n" for p, c in files.items()}}, "Concurrent write")
""")
    hook.chmod(0o755)


def assert_clean_and_in_sync(repo: Path) -> None:
    """`repo` has no uncommitted changes, no rebase in progress, and matches its remote."""
    git(repo, "fetch", "--quiet")
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "@{upstream}")


def race_runs(repo: Path) -> int:
    """How many times the race_on_commit hook has pushed."""
    counter = repo / ".git" / "race-count"
    return int(counter.read_text()) if counter.exists() else 0


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


@contextlib.contextmanager
def as_oauth_user(user_id: str):
    """Run as an OAuth'd user, the way the /mcp bearer-auth middleware sets it up."""
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    token = AccessToken(token="t", client_id="claude", scopes=[], subject=user_id)
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)


def referenced_tool_names(guidance: str) -> set[str]:
    """Tool-like names a guidance text tells the model to call: `snake_case` or
    **snake_case** (at least one underscore, so plain bold words don't count)."""
    pairs = re.findall(r"`([a-z]+(?:_[a-z]+)+)`|\*\*([a-z]+(?:_[a-z]+)+)\*\*", guidance)
    return {name for pair in pairs for name in pair if name}
