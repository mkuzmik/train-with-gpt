"""Read goals tool."""

import asyncio
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import current_user_id, git_pull_and_read, read_file_if_exists, user_scoped_goals_file, training_repo_not_configured_message


def read_goals_tool() -> Tool:
    """Return the read_goals tool definition."""
    return Tool(
        name="read_goals",
        description="Read the user's saved training goals. Use this to understand what the user is working towards and provide context-aware coaching.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def read_goals_handler(arguments: dict) -> list[TextContent]:
    """Handle read_goals tool calls."""
    try:
        # Check if training repo is configured
        if not config.training_repo_path:
            return [TextContent(type="text", text=training_repo_not_configured_message())]
        
        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]
        
        # Pull first to get the latest, and read the goals under the same lock
        goals_file, _ = user_scoped_goals_file(repo_path, current_user_id())
        pull_output, content = await asyncio.to_thread(
            git_pull_and_read, repo_path, lambda: read_file_if_exists(goals_file)
        )

        if content is None:
            return [TextContent(type="text", text="ℹ️ No goals saved yet.\n\nUse **discuss_goals** to start a conversation about training goals, then **save_goals** to save them.")]

        # Add pull info if there were updates
        if pull_output:
            content = f"_{pull_output}_\n\n{content}"
        
        return [TextContent(type="text", text=content)]
    
    except Exception as e:
        print(f"Error reading goals: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
