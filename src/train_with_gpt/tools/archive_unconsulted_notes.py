"""Archive unconsulted notes tool."""

import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config


def archive_unconsulted_notes_tool() -> Tool:
    """Return the archive_unconsulted_notes tool definition."""
    return Tool(
        name="archive_unconsulted_notes",
        description="Move all notes from _not_consulted to _not_consulted/_archived after they have been processed in a consultation. Call this after reading and discussing unconsulted notes.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def archive_unconsulted_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle archive_unconsulted_notes tool calls."""
    try:
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.")]

        repo_path = Path(config.training_repo_path)
        unconsulted_dir = repo_path / "_not_consulted"

        if not unconsulted_dir.exists():
            return [TextContent(type="text", text="ℹ️ No _not_consulted directory found.")]

        note_files = list(unconsulted_dir.glob("*.md"))

        if not note_files:
            return [TextContent(type="text", text="ℹ️ No notes to archive.")]

        # Create archive directory
        archive_dir = unconsulted_dir / "_archived"
        archive_dir.mkdir(exist_ok=True)

        # Move files
        moved = []
        for note_file in note_files:
            dest = archive_dir / note_file.name
            note_file.rename(dest)
            moved.append(note_file.name)

        return [TextContent(type="text", text=f"✅ Archived {len(moved)} note(s) to _not_consulted/_archived/:\n\n" + "\n".join(f"- {f}" for f in moved))]

    except Exception as e:
        print(f"Error archiving unconsulted notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
