"""Helper functions for train-with-gpt server."""

import re
import subprocess
from pathlib import Path
from typing import Optional


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
    "ℹ️ Wellness data (sleep, HRV, resting heart rate) isn't available for accounts "
    "connected via Strava - Strava has no wellness data at all. This is only available "
    "through the personal intervals.icu-backed setup."
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


def git_pull(repo_path: Path) -> str:
    """
    Perform git pull in the repository.
    
    Returns:
        Pull status message or None if no message needed
    """
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )
        pull_output = result.stdout.strip()
        return pull_output if pull_output and "already up to date" not in pull_output.lower() else None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        # Handle bytes or string
        if isinstance(error_msg, bytes):
            error_msg = error_msg.decode('utf-8', errors='ignore')
        # Only show error if it's not about missing remote/tracking
        if "no tracking information" not in error_msg.lower() and "no remote" not in error_msg.lower():
            return f"(Note: git pull had issues - {error_msg})"
        return None


def git_add_commit_push(repo_path: Path, file_path: str, commit_message: str) -> str:
    """
    Add, commit, and push changes to git repository.
    
    Args:
        repo_path: Path to git repository
        file_path: Path to file relative to repo (e.g., "goals.md" or "notes/file.md")
        commit_message: Git commit message
    
    Returns:
        Status message about the operation
    """
    try:
        # Git add
        subprocess.run(
            ["git", "add", file_path],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Git commit
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Git push
        push_status = ""
        try:
            subprocess.run(
                ["git", "push"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            push_status = " and pushed to remote"
        except subprocess.CalledProcessError as push_error:
            error_msg = push_error.stderr.strip() if push_error.stderr else str(push_error)
            if "no upstream branch" in error_msg.lower() or "no configured push destination" in error_msg.lower():
                push_status = "\n\n⚠️ Note: Could not push (no remote configured). Changes are saved locally."
            else:
                push_status = f"\n\n⚠️ Note: Could not push to remote: {error_msg}"
        
        return push_status
        
    except subprocess.CalledProcessError as e:
        # If commit fails (e.g., no changes), check if it's because nothing to
        # commit - git reports that on stdout, not stderr.
        output = (e.stdout or b"") + (e.stderr or b"")
        if "nothing to commit" in output.decode('utf-8', errors='ignore').lower():
            return "\n\n(No changes to commit - content unchanged)"
        else:
            raise
