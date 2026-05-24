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
                "storage_type": {
                    "type": "string",
                    "enum": ["git", "directory"],
                    "description": "Storage type: 'git' (default) requires a git repo and does commit/push, 'directory' uses a plain directory without git (e.g. for Obsidian vaults synced via iCloud)",
                },
            },
            "required": ["repo_path"],
        },
    )


async def setup_training_repo_handler(arguments: dict) -> list[TextContent]:
    """Handle setup_training_repo tool calls."""
    try:
        repo_path = arguments.get("repo_path", "")
        storage_type = arguments.get("storage_type", "git")

        if not repo_path:
            return [TextContent(type="text", text="❌ Error: No repository path provided")]

        if storage_type not in ("git", "directory"):
            return [TextContent(type="text", text="❌ Error: storage_type must be 'git' or 'directory'")]

        # Expand user path and convert to absolute
        repo_path = Path(repo_path).expanduser().absolute()

        # Verify it exists and is a directory
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Path does not exist: {repo_path}")]

        if not repo_path.is_dir():
            return [TextContent(type="text", text=f"❌ Error: Path is not a directory: {repo_path}")]

        # Verify it's a git repository (only for git storage type)
        if storage_type == "git":
            git_dir = repo_path / ".git"
            if not git_dir.exists():
                return [TextContent(type="text", text=f"❌ Error: Not a git repository: {repo_path}\n\nPlease initialize it with: git init")]

        # Save to config
        config.save(training_repo_path=str(repo_path), storage_type=storage_type)

        if storage_type == "directory":
            return [TextContent(type="text", text=f"✅ Training directory configured: {repo_path}\n\nStorage type: directory (no git, synced externally e.g. iCloud)\n\nYou can now use **read_goals** and **save_goals** to manage your training notes.")]
        else:
            return [TextContent(type="text", text=f"✅ Training repository configured: {repo_path}\n\nStorage type: git (commit & push on save)\n\nYou can now use **read_goals** and **save_goals** to manage your training notes in this git repository.")]

    except Exception as e:
        print(f"Error setting up training repo: {e}", file=__import__('sys').stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
