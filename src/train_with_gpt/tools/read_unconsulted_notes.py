"""Read unconsulted notes tool."""

import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config


def read_unconsulted_notes_tool() -> Tool:
    """Return the read_unconsulted_notes tool definition."""
    return Tool(
        name="read_unconsulted_notes",
        description="Read all notes from the _not_consulted directory. These are raw notes the user jotted down after workouts that haven't been discussed in a consultation yet. After processing them in a consultation, they should be archived using archive_unconsulted_notes.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def read_unconsulted_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle read_unconsulted_notes tool calls."""
    try:
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first.")]

        repo_path = Path(config.training_repo_path)
        unconsulted_dir = repo_path / "_not_consulted"

        if not unconsulted_dir.exists():
            return [TextContent(type="text", text="ℹ️ No _not_consulted directory found. Nothing to review.")]

        # Get all .md files
        note_files = sorted(unconsulted_dir.glob("*.md"))

        if not note_files:
            return [TextContent(type="text", text="ℹ️ No unconsulted notes. You're all caught up.")]

        # Read all notes
        all_notes = []
        for note_file in note_files:
            with open(note_file, 'r') as f:
                content = f.read().strip()
            all_notes.append(f"## 📝 {note_file.name}\n\n{content}")

        combined = "\n\n---\n\n".join(all_notes)

        return [TextContent(type="text", text=f"Found {len(note_files)} unconsulted note(s):\n\n{combined}")]

    except Exception as e:
        print(f"Error reading unconsulted notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
