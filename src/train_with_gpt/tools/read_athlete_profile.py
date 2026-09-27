"""Read athlete profile tool."""

import asyncio
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import (
    current_user_id,
    git_pull_and_read,
    read_file_if_exists,
    sync_note_for_caller,
    training_repo_not_configured_message,
    user_scoped_profile_file,
)

NO_PROFILE_MESSAGE = (
    "ℹ️ No athlete profile saved yet.\n\n"
    "Offer to build one with the athlete: **build_athlete_profile** walks through the "
    "interview, the check against their data and the confirmation, then **save_athlete_profile** saves it."
)


def read_athlete_profile_tool() -> Tool:
    """Return the read_athlete_profile tool definition."""
    return Tool(
        name="read_athlete_profile",
        description=(
            "Read the athlete profile: the coach's confirmed conclusions about the athlete "
            "(background, race results and PBs, tests, health, constraints, strengths and "
            "limiters, what works, preferences). start_consultation already includes it; "
            "call this to re-read it later in a chat, e.g. before proposing an update."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def read_athlete_profile_handler(arguments: dict) -> list[TextContent]:
    """Handle read_athlete_profile tool calls."""
    try:
        if not config.training_repo_path:
            return [TextContent(type="text", text=training_repo_not_configured_message())]

        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]

        # Pull first to get the latest, and read under the same lock
        profile_file, _ = user_scoped_profile_file(repo_path, current_user_id())
        pull_output, content = await asyncio.to_thread(
            git_pull_and_read, repo_path, lambda: read_file_if_exists(profile_file)
        )

        if content is None:
            return [TextContent(type="text", text=NO_PROFILE_MESSAGE)]

        pull_output = sync_note_for_caller(pull_output, current_user_id())
        if pull_output:
            content = f"_{pull_output}_\n\n{content}"

        return [TextContent(type="text", text=content)]

    except Exception as e:
        print(f"Error reading athlete profile: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
