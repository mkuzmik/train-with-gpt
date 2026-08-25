"""List consultation notes tool."""

import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import git_pull, extract_note_headline


def list_consultation_notes_tool() -> Tool:
    """Return the list_consultation_notes tool definition."""
    return Tool(
        name="list_consultation_notes",
        description=(
            "List all consultation notes as a compact dated index (date + one-line "
            "headline per note), without their full text. Use this first to see what "
            "history exists, then call read_consultation_notes with a since/until range "
            "or note_date to pull specific notes in full."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def list_consultation_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle list_consultation_notes tool calls."""
    try:
        # Check if training repo is configured
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]

        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]

        # Git pull first to get latest
        pull_output = git_pull(repo_path)

        notes_dir = repo_path / "notes"

        if not notes_dir.exists():
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]

        # Get all .md files in notes directory, most recent first
        note_files = sorted(notes_dir.glob("*.md"), reverse=True)

        if not note_files:
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]

        lines = []
        for note_file in note_files:
            with open(note_file, 'r') as f:
                text = f.read()
            date = note_file.stem[:10]  # YYYY-MM-DD from YYYY-MM-DD-HH-MM-SS
            headline = extract_note_headline(text)
            lines.append(f"{date} — {headline}")

        earliest = note_files[-1].stem[:10]
        latest = note_files[0].stem[:10]

        summary = (
            f"{len(note_files)} consultation note(s), spanning {earliest} to {latest}.\n\n"
            "Call read_consultation_notes with since/until (YYYY-MM-DD) or note_date to read "
            "specific notes in full, or all=true for the complete history."
        )

        content = "\n".join(lines)

        if pull_output:
            summary = f"_{pull_output}_\n\n{summary}"

        return [TextContent(type="text", text=f"{summary}\n\n{content}")]

    except Exception as e:
        print(f"Error listing consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
