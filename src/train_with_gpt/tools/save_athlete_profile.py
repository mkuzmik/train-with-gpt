"""Save athlete profile tool."""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import (
    GitSyncError,
    current_user_id,
    git_save_file,
    training_repo_not_configured_message,
    user_scoped_profile_file,
)

# The profile is loaded into every consultation (start_consultation includes
# it), so it has to stay short. ~5,500 characters is the target; the hard
# limit leaves room for a longer race-results table before refusing.
PROFILE_TARGET_CHARS = 5_500
PROFILE_MAX_CHARS = 8_000

PROFILE_SECTIONS = (
    "Background",
    "Race results",
    "Tests",
    "Health",
    "Constraints",
    "Strengths and limiters",
    "What works",
    "Preferences",
)

# The title and "Saved:" line the tool adds, which the model may send back
# when it edits a profile it read: the tool adds fresh ones.
_TITLE_RE = re.compile(r"\A\s*#\s*athlete profile[ \t]*(\n\s*saved:[^\n]*)?(\n|\Z)", re.IGNORECASE)


def save_athlete_profile_tool() -> Tool:
    """Return the save_athlete_profile tool definition."""
    headings = ", ".join(f"`## {name}`" for name in PROFILE_SECTIONS)
    return Tool(
        name="save_athlete_profile",
        description=(
            "Save the athlete profile: the coach's conclusions about who the athlete is, "
            "built with them (see build_athlete_profile). Only call this after the athlete "
            "has seen and confirmed the full text. It replaces the whole saved profile, so "
            "always send the complete profile, not just a changed part. "
            "Content: conclusions and durable facts only - background, race results and "
            "PBs (actual races, never inferred from training efforts), tests, health "
            "(current issues, relevant history, recurring patterns such as \"ferritin drops "
            "below 40 without supplementation\"; no raw lab panels or dated series of values), "
            "constraints, strengths and limiters, what works, preferences. No weekly stats "
            "(volume, fitness/form, resting HR, HRV, sleep numbers), no gear: the data tools "
            f"recompute those. Use these sections: {headings}. Keep it short, about "
            f"{PROFILE_TARGET_CHARS:,} characters (hard limit {PROFILE_MAX_CHARS:,}); details "
            "belong in consultation notes. Goals and the current training block go in "
            "save_goals, not here."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The complete profile text in Markdown, as confirmed by the athlete, "
                        "starting with the first `## ` section (the title and save date are added)."
                    ),
                },
            },
            "required": ["content"],
        },
    )


async def save_athlete_profile_handler(arguments: dict) -> list[TextContent]:
    """Handle save_athlete_profile tool calls."""
    try:
        if not config.training_repo_path:
            return [TextContent(type="text", text=training_repo_not_configured_message())]

        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]

        profile_text = _TITLE_RE.sub("", arguments.get("content") or "", count=1).strip()
        if not profile_text:
            return [TextContent(type="text", text="❌ Error: No profile content provided")]
        if len(profile_text) > PROFILE_MAX_CHARS:
            return [TextContent(type="text", text=(
                f"❌ Error: The profile was NOT saved: it is {len(profile_text):,} characters, over the "
                f"{PROFILE_MAX_CHARS:,} limit (aim for about {PROFILE_TARGET_CHARS:,}). It is loaded into "
                "every consultation, so keep conclusions and durable facts only: move details, older race "
                "results and stories to consultation notes (save_consultation_notes), shorten, and save again."
            ))]

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"""# Athlete profile
Saved: {timestamp}

{profile_text}
"""

        # athlete/<user_id>.md for OAuth'd users, athlete-profile.md at the
        # repo root for the personal path. Saving replaces the whole file, like
        # goals: if another device saved concurrently, the last save wins.
        profile_file, relative_path = user_scoped_profile_file(repo_path, current_user_id())

        push_status = await asyncio.to_thread(
            git_save_file, repo_path, relative_path, content, f"Update athlete profile - {timestamp}"
        )

        return [TextContent(type="text", text=f"✅ Athlete profile saved, committed{push_status}: {profile_file}\n\nIt will be included at the start of every consultation.")]

    except GitSyncError as e:
        return [TextContent(type="text", text=f"❌ Error: The athlete profile was not saved. {e}")]

    except Exception as e:
        print(f"Error saving athlete profile: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
