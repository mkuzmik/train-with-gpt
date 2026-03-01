"""Setup training repository tool."""

from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config


def setup_training_repo_tool() -> Tool:
    """Return the setup_training_repo tool definition."""
    return Tool(
        name="setup_training_repo",
        description="Configure the local git repository path where training notes and goals will be stored. Must be called before using read_goals or save_goals.",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the local git repository for training notes",
                },
            },
            "required": ["repo_path"],
        },
    )


async def setup_training_repo_handler(arguments: dict) -> list[TextContent]:
    """Handle setup_training_repo tool calls."""
    try:
        repo_path = arguments.get("repo_path", "")
        if not repo_path:
            return [TextContent(type="text", text="❌ Error: No repository path provided")]
        
        # Expand user path and convert to absolute
        repo_path = Path(repo_path).expanduser().absolute()
        
        # Verify it exists and is a directory
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Path does not exist: {repo_path}")]
        
        if not repo_path.is_dir():
            return [TextContent(type="text", text=f"❌ Error: Path is not a directory: {repo_path}")]
        
        # Verify it's a git repository
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            return [TextContent(type="text", text=f"❌ Error: Not a git repository: {repo_path}\n\nPlease initialize it with: git init")]
        
        # Save to config
        config.save(training_repo_path=str(repo_path))
        
        return [TextContent(type="text", text=f"✅ Training repository configured: {repo_path}\n\nYou can now use **read_goals** and **save_goals** to manage your training notes in this git repository.")]
    
    except Exception as e:
        print(f"Error setting up training repo: {e}", file=__import__('sys').stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
