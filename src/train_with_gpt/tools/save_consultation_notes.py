"""Save consultation notes tool."""

import asyncio
import secrets
import sys
from datetime import datetime
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import GitSyncError, current_user_id, git_save_file, user_scoped_notes_dir


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
        
        # User-scoped subdir for OAuth'd multi-user sessions, repo root for
        # the personal path
        notes_dir, notes_prefix = user_scoped_notes_dir(repo_path, current_user_id())

        # Timestamped filename, plus a short random suffix so two devices
        # saving in the same second never collide. Tools read the date from
        # the first 10 characters, so older YYYY-MM-DD-HH-MM-SS.md names and
        # these sort and parse the same way.
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d-%H-%M-%S")
        timestamp_display = now.strftime("%Y-%m-%d %H:%M:%S")
        filename = f"{timestamp}-{secrets.token_hex(3)}.md"
        notes_file = notes_dir / filename

        content = f"""# Consultation Notes
Date: {timestamp_display}

{notes}
"""

        # Sync, write, commit and push (in a worker thread; git_save_file
        # serializes access to the repo)
        relative_path = f"{notes_prefix}/{filename}"
        push_status = await asyncio.to_thread(
            git_save_file, repo_path, relative_path, content, f"Add consultation notes - {timestamp_display}"
        )

        return [TextContent(type="text", text=f"✅ Consultation notes saved, committed{push_status}: {notes_file}\n\nThese notes are now part of your training history and can be referenced in future consultations.")]

    except GitSyncError as e:
        return [TextContent(type="text", text=f"❌ Error: Consultation notes were not saved. {e}")]

    except Exception as e:
        print(f"Error saving consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
