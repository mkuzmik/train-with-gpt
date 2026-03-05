"""Read consultation notes tool."""

import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import git_pull


def read_consultation_notes_tool() -> Tool:
    """Return the read_consultation_notes tool definition."""
    return Tool(
        name="read_consultation_notes",
        description="Read all previous consultation notes to provide complete context and continuity across all sessions. Always returns ALL notes.",
        inputSchema={
            "type": "object",
            "properties": {},
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
        
        # Git pull first to get latest
        pull_output = git_pull(repo_path)
        
        notes_dir = repo_path / "notes"
        
        if not notes_dir.exists():
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]
        
        # Get all .md files in notes directory
        note_files = sorted(notes_dir.glob("*.md"), reverse=True)  # Most recent first
        
        if not note_files:
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]
        
        # Read all notes
        all_notes = []
        for note_file in note_files:
            with open(note_file, 'r') as f:
                all_notes.append(f.read())
        
        # Combine notes with separator
        content = "\n\n---\n\n".join(all_notes)
        
        # Add pull info if there were updates
        if pull_output:
            content = f"_{pull_output}_\n\n{content}"
        
        summary = f"Found {len(note_files)} consultation note(s)"
        
        return [TextContent(type="text", text=f"{summary}\n\n{content}")]
    
    except Exception as e:
        print(f"Error reading consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
