"""Helper functions for train-with-gpt server."""

import subprocess
from pathlib import Path


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
        # If commit fails (e.g., no changes), check if it's because nothing to commit
        if "nothing to commit" in e.stderr.decode('utf-8', errors='ignore').lower():
            return "\n\n(No changes to commit - content unchanged)"
        else:
            raise
