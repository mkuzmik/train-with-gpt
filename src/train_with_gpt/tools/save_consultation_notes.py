"""Save consultation notes tool."""

import sys
from datetime import datetime
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import git_add_commit_push


def save_consultation_notes_tool() -> Tool:
    """Return the save_consultation_notes tool definition."""
    return Tool(
        name="save_consultation_notes",
        description="Save consultation notes from the current conversation. Creates a new timestamped file in the notes/ directory. Each consultation is immutable once saved.",
        inputSchema={
            "type": "object",
            "properties": {
                "notes": {
                    "type": "string",
                    "description": "Natural language summary of the consultation including discussion topics, recommendations, and next steps",
                },
            },
            "required": ["notes"],
        },
    )


async def save_consultation_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle save_consultation_notes tool calls."""
    try:
        # Check if training repo is configured
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]
        
        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]
        
        notes = arguments.get("notes", "")
        if not notes:
            return [TextContent(type="text", text="❌ Error: No notes provided")]
        
        # Create notes directory if it doesn't exist
        notes_dir = repo_path / "notes"
        notes_dir.mkdir(exist_ok=True)
        
        # Create timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        timestamp_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        notes_file = notes_dir / f"{timestamp}.md"
        
        # Write consultation notes
        content = f"""# Consultation Notes
Date: {timestamp_display}

{notes}
"""
        
        with open(notes_file, 'w') as f:
            f.write(content)
        
        # Git add, commit, and push
        relative_path = f"notes/{timestamp}.md"
        push_status = git_add_commit_push(repo_path, relative_path, f"Add consultation notes - {timestamp_display}")
        
        return [TextContent(type="text", text=f"✅ Consultation notes saved, committed{push_status}: {notes_file}\n\nThese notes are now part of your training history and can be referenced in future consultations.")]
    
    except Exception as e:
        print(f"Error saving consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
