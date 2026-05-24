"""Archive unconsulted notes tool."""

import sys
import subprocess
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config


def archive_unconsulted_notes_tool() -> Tool:
    """Return the archive_unconsulted_notes tool definition."""
    return Tool(
        name="archive_unconsulted_notes",
        description="Delete all notes from _not_consulted after they have been processed in a consultation. Moves them to the system trash. Call this after reading and discussing unconsulted notes.",
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

        # Move files to system trash using macOS `trash` command
        moved = []
        for note_file in note_files:
            try:
                subprocess.run(
                    ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{note_file}"'],
                    check=True,
                    capture_output=True,
                )
                moved.append(note_file.name)
            except subprocess.CalledProcessError:
                # Fallback: just delete if trash fails
                note_file.unlink()
                moved.append(note_file.name)

        return [TextContent(type="text", text=f"✅ Moved {len(moved)} note(s) to trash:\n\n" + "\n".join(f"- {f}" for f in moved))]

    except Exception as e:
        print(f"Error archiving unconsulted notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
