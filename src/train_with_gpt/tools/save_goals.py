"""Save goals tool."""

import sys
from datetime import datetime
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import git_add_commit_push


def save_goals_tool() -> Tool:
    """Return the save_goals tool definition."""
    return Tool(
        name="save_goals",
        description="Save the user's training goals in natural language format. Write a clear, comprehensive summary of goals, context, and constraints.",
        inputSchema={
            "type": "object",
            "properties": {
                "goals_text": {
                    "type": "string",
                    "description": "Natural language description of the user's training goals, current state, constraints, and context",
                },
            },
            "required": ["goals_text"],
        },
    )


async def save_goals_handler(arguments: dict) -> list[TextContent]:
    """Handle save_goals tool calls."""
    try:
        # Check if training repo is configured
        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]
        
        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]
        
        goals_text = arguments.get("goals_text", "")
        if not goals_text:
            return [TextContent(type="text", text="❌ Error: No goals provided")]
        
        # Add timestamp header
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"""# Training Goals
Saved: {timestamp}

{goals_text}
"""
        
        # Write to goals.md in the repo
        goals_file = repo_path / "goals.md"
        with open(goals_file, 'w') as f:
            f.write(content)
        
        # Git add, commit, and push
        push_status = git_add_commit_push(repo_path, "goals.md", f"Update training goals - {timestamp}")
        
        return [TextContent(type="text", text=f"✅ Goals saved, committed{push_status}: {goals_file}\n\nYou can now analyze activities and provide coaching advice in the context of these goals.")]
    
    except Exception as e:
        print(f"Error saving goals: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
