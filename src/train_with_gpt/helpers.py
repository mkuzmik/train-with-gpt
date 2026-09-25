"""Helper functions for train-with-gpt server."""

import random
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def current_user_id() -> Optional[str]:
    """
    Resolve the OAuth-authenticated user's id for the current request, if any.

    Set only on the multi-user HTTP/OAuth path (see oauth_provider.py) - the
    stdio and local-HTTP personal paths have no access token in context, so
    this returns None there, keeping notes/goals at their existing root-level
    paths for those.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    return token.subject if token else None


def user_scoped_notes_dir(repo_path: Path, user_id: Optional[str]) -> tuple[Path, str]:
    """Returns (notes_dir, relative_dir_prefix_for_git) for the given user, if any."""
    if user_id:
        return repo_path / "notes" / user_id, f"notes/{user_id}"
    return repo_path / "notes", "notes"


def user_scoped_goals_file(repo_path: Path, user_id: Optional[str]) -> tuple[Path, str]:
    """Returns (goals_file, relative_path_for_git) for the given user, if any."""
    if user_id:
        return repo_path / "goals" / f"{user_id}.md", f"goals/{user_id}.md"
    return repo_path / "goals.md", "goals.md"


NO_WELLNESS_DATA_MESSAGE = (
    "ℹ️ Wellness data (sleep, HRV, resting heart rate) isn't available: Strava has no "
    "wellness data. To add it, connect intervals.icu: disconnect and reconnect this "
    "connector in Claude's settings, and paste your intervals.icu API key on the "
    "page shown after the Strava login."
)


_NOTES_HEADER_RE = re.compile(r"^#\s*consultation notes\s*$", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^date:\s*", re.IGNORECASE)
_SKIP_LINE_RE = re.compile(r"^(#{1,6}\s|={3,}$|-{3,}$)")


def extract_note_headline(text: str, max_length: int = 200) -> str:
    """
    Derive a short one-line headline from a consultation note's content.

    Works across the note's evolving formats without needing a fixed section
    name: strips the standard "# Consultation Notes / Date: ..." header, then
    skips markdown headers, banner lines (====, ----), and all-caps section
    titles (e.g. "HEADLINE"), collecting the first bit of real prose. Does
    not modify the note itself.
    """
    lines = text.splitlines()

    if lines and _NOTES_HEADER_RE.match(lines[0].strip()):
        lines = lines[1:]
    if lines and _DATE_LINE_RE.match(lines[0].strip()):
        lines = lines[1:]

    content_parts = []
    length = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue
        if stripped.isupper():
            continue
        content_parts.append(stripped)
        length += len(stripped) + 1
        if length >= max_length:
            break

    snippet = " ".join(content_parts) if content_parts else "(no summary available)"

    if len(snippet) <= max_length:
        return snippet

    truncated = snippet[:max_length].rsplit(" ", 1)[0]
    return f"{truncated}…"


def calculate_zone_distribution(stream_data: list, zone_boundaries: list) -> dict:
    """
    Calculate time spent in each zone.
    
    Args:
        stream_data: Array of HR or power values
        zone_boundaries: List of zone upper boundaries [z1_max, z2_max, z3_max, z4_max, z5_max]
    
    Returns:
        Dict with zone numbers as keys and seconds in each zone as values
    """
    if not stream_data or not zone_boundaries:
        return {}
    
    zone_time = {i+1: 0 for i in range(len(zone_boundaries) + 1)}
    
    for value in stream_data:
        if value is None:
            continue
        
        zone = len(zone_boundaries) + 1  # Default to highest zone
        for i, boundary in enumerate(zone_boundaries):
            if value <= boundary:
                zone = i + 1
                break
        
        zone_time[zone] += 1  # Each point represents 1 second typically
    
    return zone_time


# --- Training repo sync ------------------------------------------------------------
#
# The training repo is written concurrently: several requests in one process
# (phone and desktop hitting the same server), and other clones pushing to the
# same remote (other server instances, the personal/stdio path on a laptop).
#
# - Within a process, every git operation on a working tree holds that repo's
#   lock. The tools run git_pull/git_save_file in worker threads, so the lock
#   is what serializes them - not the event loop.
# - Across clones, a save is "sync, write, commit, push"; if the push is
#   rejected because someone else pushed first, our commit is dropped and the
#   same write is re-applied on top of the fresh remote state.

GIT_SAVE_ATTEMPTS = 5

_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


class GitSyncError(Exception):
    """A save couldn't be completed; the message says what happened."""


def _repo_lock(repo_path: Path) -> threading.Lock:
    key = str(Path(repo_path).resolve())
    with _repo_locks_guard:
        return _repo_locks.setdefault(key, threading.Lock())


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_path, capture_output=True, text=True)


def _output(result: subprocess.CompletedProcess) -> str:
    return result.stderr.strip() or result.stdout.strip()


def _head(repo_path: Path) -> Optional[str]:
    result = _git(repo_path, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _sync_with_remote(repo_path: Path) -> tuple[Optional[str], Optional[str]]:
    """
    Bring the clone up to date with its upstream branch.

    Returns (updates, warning): a summary of the files that came in from the
    remote, and a note about anything else the user should know. Either may be None.

    This rebases rather than hard-resetting: on the personal/stdio path the
    clone is the user's own checkout, and on the server a local commit that
    isn't on the remote is content whose push failed earlier. So local commits
    are replayed on top of the remote (and go out with the next push), and
    uncommitted edits are autostashed. If replaying conflicts, the rebase is
    aborted, the local commits are parked on a backup branch and the clone is
    reset to the remote, so it never stays mid-rebase or diverged.
    """
    if _git(repo_path, "rev-parse", "--abbrev-ref", "@{upstream}").returncode != 0:
        return None, None  # no remote/upstream: a local-only repo

    fetch = _git(repo_path, "fetch", "--quiet")
    if fetch.returncode != 0:
        return None, f"(Note: git pull had issues - {_output(fetch)})"

    before = _head(repo_path)
    rebase = _git(repo_path, "rebase", "--autostash", "@{upstream}")
    if rebase.returncode == 0:
        changed = _git(repo_path, "diff", "--name-only", before, "HEAD").stdout.split() if before else []
        if not changed:
            return None, None
        shown = ", ".join(changed[:10]) + (f" and {len(changed) - 10} more" if len(changed) > 10 else "")
        return f"Pulled updates from the remote: {shown}", None

    _git(repo_path, "rebase", "--abort")
    error = _output(rebase)
    unpushed = _unpushed_count(repo_path)
    if unpushed == 0:
        raise GitSyncError(f"Could not sync with the remote: {error}")

    branch = f"unsynced-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{random.randrange(16**4):04x}"
    _git(repo_path, "branch", branch)
    # Uncommitted edits (restored by the aborted rebase's autostash) could
    # block the reset, so set them aside too.
    stashed = ""
    if _git(repo_path, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        _git(repo_path, "stash", "push", "-m", f"Uncommitted edits set aside while syncing ({branch})")
        stashed = " Uncommitted edits were stashed (see `git stash list`)."
    reset = _git(repo_path, "reset", "--keep", "@{upstream}")
    if reset.returncode != 0:
        raise GitSyncError(
            f"Could not sync with the remote: local commits conflict with it ({error}), "
            f"and resetting to the remote failed: {_output(reset)}"
        )
    return None, (
        f"⚠️ {unpushed} local commit(s) conflicted with newer changes on the remote. "
        f"They were moved to local branch '{branch}', and this clone now matches the remote.{stashed}"
    )


def git_pull_and_read(repo_path: Path, read: Callable[[], T]) -> tuple[Optional[str], T]:
    """
    Sync the training repo with its remote, then call `read` under the same
    repo lock, so it never sees a concurrent save's half-written file. Syncing
    also recovers a clone that had diverged (see _sync_with_remote).

    Returns:
        (note, read()) - the note tells the user what came in or what went
        wrong, and is None when there's nothing to say
    """
    with _repo_lock(repo_path):
        try:
            updates, warning = _sync_with_remote(repo_path)
            note = "\n\n".join(part for part in (warning, updates) if part) or None
        except GitSyncError as e:
            note = f"(Note: {e})"
        return note, read()


def git_pull(repo_path: Path) -> Optional[str]:
    """Sync the training repo with its remote; returns a note for the user, or None."""
    return git_pull_and_read(repo_path, lambda: None)[0]


def read_note_files(notes_dir: Path) -> list[tuple[str, str]]:
    """(filename stem, text) of every note in `notes_dir`, newest first."""
    if not notes_dir.exists():
        return []
    return [(path.stem, path.read_text()) for path in sorted(notes_dir.glob("*.md"), reverse=True)]


def read_file_if_exists(path: Path) -> Optional[str]:
    return path.read_text() if path.exists() else None


def _lost_push_race(error: str) -> bool:
    """
    Was our push refused because someone else pushed first? That's a
    non-fast-forward rejection, or the remote's ref moving under an update in
    flight. Other rejections (e.g. a pre-receive hook or branch policy)
    won't go away by retrying.
    """
    error = error.lower()
    return any(s in error for s in (
        "fetch first", "non-fast-forward", "cannot lock ref", "incorrect old value",
    ))


def _unpushed_count(repo_path: Path) -> int:
    result = _git(repo_path, "rev-list", "--count", "@{upstream}..HEAD")
    return int(result.stdout.strip()) if result.returncode == 0 else 0


def git_save_file(repo_path: Path, file_path: str, content: str, commit_message: str) -> str:
    """
    Write `content` to `file_path`, commit it and push it, safely under
    concurrent writers.

    Under the repo lock: sync with the remote, write, commit, push. If the push
    is rejected because another clone pushed first, our commit is dropped and
    the same write is re-applied on the new remote state, up to
    GIT_SAVE_ATTEMPTS times with a short backoff. For a file that's replaced
    wholesale (goals) that deliberately means the last writer wins; notes get
    unique filenames, so they never overwrite each other.

    Args:
        repo_path: Path to git repository
        file_path: Path to file relative to repo (e.g., "goals.md" or "notes/file.md")
        content: The file's full new content
        commit_message: Git commit message

    Returns:
        Status message to append to "saved, committed"

    Raises:
        GitSyncError: the content was NOT saved; the clone is left matching the remote.
    """
    target = Path(repo_path) / file_path
    warnings = []
    last_error = ""

    with _repo_lock(repo_path):
        for attempt in range(1, GIT_SAVE_ATTEMPTS + 1):
            _, warning = _sync_with_remote(repo_path)
            if warning and warning not in warnings:
                warnings.append(warning)
            notes = "".join(f"\n\n{w}" for w in warnings)

            base = _head(repo_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            add = _git(repo_path, "add", file_path)
            if add.returncode != 0:
                raise GitSyncError(f"Could not stage {file_path}: {_output(add)}")
            commit = _git(repo_path, "commit", "-m", commit_message)
            if commit.returncode != 0:
                # git reports "nothing to commit" on stdout, not stderr
                if "nothing to commit" not in (commit.stdout + commit.stderr).lower():
                    raise GitSyncError(f"Could not commit {file_path}: {_output(commit)}")
                if _unpushed_count(repo_path) == 0:
                    return f"\n\n(No changes to commit - content unchanged){notes}"
                # Content unchanged, but an earlier commit (e.g. this same
                # content, whose push failed) is still waiting: push it.

            push = _git(repo_path, "push")
            if push.returncode == 0:
                return f" and pushed to remote{notes}"

            last_error = _output(push)
            if "no upstream branch" in last_error.lower() or "no configured push destination" in last_error.lower():
                return f"\n\n⚠️ Note: Could not push (no remote configured). Changes are saved locally.{notes}"
            if not _lost_push_race(last_error):
                # e.g. the remote is unreachable: keep the commit - the next
                # save replays it on top of the remote and tries to push it again.
                return (
                    f"\n\n⚠️ Note: Could not push to remote: {last_error}\n"
                    f"The commit is kept locally; the next save will try to push it again.{notes}"
                )

            # Someone else pushed first: drop our commit, re-apply on their state.
            if base:
                _git(repo_path, "reset", "--keep", base)
            if attempt < GIT_SAVE_ATTEMPTS:
                time.sleep(random.uniform(0.05, 0.2) * attempt)

        # Out of attempts: leave the clone matching the remote, and say so.
        try:
            _sync_with_remote(repo_path)
        except GitSyncError:
            pass
        raise GitSyncError(
            f"The remote kept changing while saving, so this was NOT saved "
            f"(gave up after {GIT_SAVE_ATTEMPTS} attempts). Please try again. "
            f"Last push error: {last_error}"
        )
