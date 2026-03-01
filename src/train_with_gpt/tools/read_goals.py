"""Read goals tool."""

import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import git_pull


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
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]
        
        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]
        
        # Git pull first to get latest
        pull_output = git_pull(repo_path)
        
        goals_file = repo_path / "goals.md"
        
        if not goals_file.exists():
            return [TextContent(type="text", text="ℹ️ No goals saved yet.\n\nUse **discuss_goals** to start a conversation about training goals, then **save_goals** to save them.")]
        
        with open(goals_file, 'r') as f:
            content = f.read()
        
        # Add pull info if there were updates
        if pull_output:
            content = f"_{pull_output}_\n\n{content}"
        
        return [TextContent(type="text", text=content)]
    
    except Exception as e:
        print(f"Error reading goals: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
