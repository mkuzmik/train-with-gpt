"""Search consultation notes tool."""

import asyncio
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import current_user_id, git_pull, user_scoped_notes_dir

_CONTEXT_LINES = 2


def search_consultation_notes_tool() -> Tool:
    """Return the search_consultation_notes tool definition."""
    return Tool(
        name="search_consultation_notes",
        description=(
            "Search all consultation notes for a keyword or phrase (case-insensitive), "
            "returning the date and a snippet of surrounding context for each match. Use "
            "this when the athlete references something specific (an injury, a race, a "
            "past decision) instead of guessing a date range with read_consultation_notes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for (case-insensitive).",
                },
            },
            "required": ["query"],
        },
    )


def _snippets_for_note(text: str, query_lower: str) -> list[str]:
    """Find matching lines in a note and group nearby matches into context snippets."""
    lines = text.splitlines()
    match_indices = [i for i, line in enumerate(lines) if query_lower in line.lower()]

    snippets = []
    i = 0
    while i < len(match_indices):
        start = max(0, match_indices[i] - _CONTEXT_LINES)
        end = min(len(lines), match_indices[i] + _CONTEXT_LINES + 1)

        # Merge subsequent matches whose context window overlaps this one.
        j = i + 1
        while j < len(match_indices) and match_indices[j] - _CONTEXT_LINES <= end:
            end = min(len(lines), match_indices[j] + _CONTEXT_LINES + 1)
            j += 1

        block = "\n".join(line for line in lines[start:end] if line.strip())
        if block:
            snippets.append(block)
        i = j

    return snippets


async def search_consultation_notes_handler(arguments: dict) -> list[TextContent]:
    """Handle search_consultation_notes tool calls."""
    try:
        query = (arguments.get("query") or "").strip()
        if not query:
            return [TextContent(type="text", text="❌ Error: 'query' is required.")]

        if not config.training_repo_path:
            return [TextContent(type="text", text="❌ Error: Training repository not configured.\n\nPlease use **setup_training_repo** first to set the location of your training notes repository.")]

        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: Training repository path no longer exists: {repo_path}")]

        pull_output = await asyncio.to_thread(git_pull, repo_path)

        notes_dir, _ = user_scoped_notes_dir(repo_path, current_user_id())

        if not notes_dir.exists():
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]

        note_files = sorted(notes_dir.glob("*.md"), reverse=True)

        if not note_files:
            return [TextContent(type="text", text="ℹ️ No consultation notes saved yet.\n\nUse **save_consultation_notes** after discussing training plans to save notes for future reference.")]

        query_lower = query.lower()
        blocks = []
        match_count = 0
        matched_dates = set()

        for note_file in note_files:
            with open(note_file, 'r') as f:
                text = f.read()

            snippets = _snippets_for_note(text, query_lower)
            if not snippets:
                continue

            date = note_file.stem[:10]
            match_count += len(snippets)
            matched_dates.add(date)
            for snippet in snippets:
                blocks.append(f"**{date}**\n{snippet}")

        if not blocks:
            return [TextContent(type="text", text=(
                f"ℹ️ No matches for \"{query}\" in any consultation note.\n\n"
                "Try a different keyword, or call **list_consultation_notes** to browse "
                "by date instead."
            ))]

        summary = (
            f"{match_count} match(es) for \"{query}\" across {len(matched_dates)} note(s):"
        )

        content = "\n\n---\n\n".join(blocks)

        if pull_output:
            summary = f"_{pull_output}_\n\n{summary}"

        return [TextContent(type="text", text=f"{summary}\n\n{content}")]

    except Exception as e:
        print(f"Error searching consultation notes: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
