"""List consultation notes tool."""

import asyncio
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import current_user_id, extract_note_headline, git_pull_and_read, read_note_files, user_scoped_notes_dir, training_repo_not_configured_message


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
            return [TextContent(type="text", text=training_repo_not_configured_message())]

        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]

        # Pull first to get the latest, and read the notes (most recent first)
        # under the same lock
        notes_dir, _ = user_scoped_notes_dir(repo_path, current_user_id())
        pull_output, notes = await asyncio.to_thread(
            git_pull_and_read, repo_path, lambda: read_note_files(notes_dir)
        )

        if not notes:
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]

        lines = []
        for stem, text in notes:
            date = stem[:10]  # YYYY-MM-DD from YYYY-MM-DD-HH-MM-SS[-suffix]
            headline = extract_note_headline(text)
            lines.append(f"{date} — {headline}")

        earliest = notes[-1][0][:10]
        latest = notes[0][0][:10]

        summary = (
            f"{len(notes)} consultation note(s), spanning {earliest} to {latest}.\n\n"
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
