"""Read consultation notes tool."""

import asyncio
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import current_user_id, git_pull_and_read, read_note_files, user_scoped_notes_dir


def read_consultation_notes_tool() -> Tool:
    """Return the read_consultation_notes tool definition."""
    return Tool(
        name="read_consultation_notes",
        description=(
            "Read previous consultation notes in full, for a chosen date range. Call "
            "list_consultation_notes first to see what history exists (dates + "
            "headlines), then pass since/until to read a range, note_date to read one "
            "specific date, or all=true to read the complete history. Calling with none "
            "of these returns guidance instead of notes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "Include notes on or after this date (YYYY-MM-DD).",
                },
                "until": {
                    "type": "string",
                    "description": "Include notes on or before this date (YYYY-MM-DD).",
                },
                "note_date": {
                    "type": "string",
                    "description": "Read only the note(s) from this exact date (YYYY-MM-DD).",
                },
                "all": {
                    "type": "boolean",
                    "description": "Read the complete consultation history, ignoring since/until/note_date.",
                },
            },
        },
    )


async def read_consultation_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle read_consultation_notes tool calls."""
    try:
        # Check if training repo is configured
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]

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

        read_all = bool(arguments.get("all"))
        since = arguments.get("since")
        until = arguments.get("until")
        note_date = arguments.get("note_date")

        if not read_all and not since and not until and not note_date:
            return [TextContent(type="text", text=(
                "ℹ️ No date range given. Call **list_consultation_notes** to see the full "
                "dated index of notes, then call this tool again with since/until "
                "(YYYY-MM-DD) for a range, note_date for one specific date, or all=true "
                "for the complete history."
            ))]

        if read_all:
            selected = notes
        elif note_date:
            selected = [(stem, text) for stem, text in notes if stem[:10] == note_date]
        else:
            selected = [
                (stem, text) for stem, text in notes
                if (not since or stem[:10] >= since) and (not until or stem[:10] <= until)
            ]

        if not selected:
            return [TextContent(type="text", text="ℹ️ No consultation notes found for that date range.")]

        all_notes = [text for _, text in selected]

        # Combine notes with separator
        content = "\n\n---\n\n".join(all_notes)

        # Add pull info if there were updates
        if pull_output:
            content = f"_{pull_output}_\n\n{content}"

        summary = f"Found {len(selected)} consultation note(s)"

        return [TextContent(type="text", text=f"{summary}\n\n{content}")]

    except Exception as e:
        print(f"Error reading consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
