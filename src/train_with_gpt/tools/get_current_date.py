"""Get current date tool."""

from datetime import datetime
from mcp.types import Tool, TextContent


def get_current_date_tool() -> Tool:
    """Return the get_current_date tool definition."""
    return Tool(
        name="get_current_date",
        description="Get the current date and day of the week. Use this to understand what 'today' means and to help calculate date ranges accurately.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def get_current_date_handler(arguments: dict) -> list[TextContent]:
    """Handle get_current_date tool calls."""
    now = datetime.now()
    
    # Format: "Saturday, March 1, 2026 (2026-03-01)"
    day = now.day  # Get day without leading zero
    formatted_date = now.strftime(f"%A, %B {day}, %Y (%Y-%m-%d)")
    
    response = f"📅 Current date: {formatted_date}\n\nUse this date as reference when the user mentions 'today', 'yesterday', 'last week', etc."
    
    return [TextContent(type="text", text=response)]
