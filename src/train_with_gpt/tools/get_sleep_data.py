"""Get sleep data range tool."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..intervals_client import IntervalsClient


def get_sleep_data_tool() -> Tool:
    """Return the get_sleep_data tool definition."""
    return Tool(
        name="get_sleep_data",
        description="Get sleep data from intervals.icu for a date range (or single date if start=end). Returns sleep duration and quality score for each night. Useful for analyzing sleep patterns and trends.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. For a single night, use same as end_date. Required.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. For a single night, use same as start_date. Required.",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )


async def get_sleep_data_handler(arguments: dict, intervals: IntervalsClient) -> list[TextContent]:
    """Handle get_sleep_data tool calls."""
    try:
        start_date_str = arguments.get("start_date")
        end_date_str = arguments.get("end_date")

        if not start_date_str or not end_date_str:
            return [TextContent(
                type="text",
                text="❌ Both start_date and end_date are required"
            )]

        # Validate and parse dates
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError as e:
            return [TextContent(
                type="text",
                text=f"❌ Invalid date format. Use YYYY-MM-DD (e.g., 2024-01-15): {e}"
            )]

        # Validate range
        if start_date > end_date:
            return [TextContent(
                type="text",
                text=f"❌ start_date ({start_date_str}) cannot be after end_date ({end_date_str})"
            )]

        # Limit to reasonable range (30 days)
        delta = (end_date - start_date).days
        if delta > 30:
            return [TextContent(
                type="text",
                text=f"❌ Date range too large ({delta} days). Maximum is 30 days."
            )]

        lines = [f"Sleep Data from {start_date_str} to {end_date_str}\n"]

        wellness_records = await intervals.get_wellness(start_date_str, end_date_str)

        sleep_records = []
        for record in wellness_records:
            sleep_secs = record.get("sleepSecs")
            if not sleep_secs:
                continue

            hours = sleep_secs // 3600
            minutes = (sleep_secs % 3600) // 60

            sleep_records.append({
                "date": record.get("id"),
                "duration_str": f"{hours}h {minutes}m",
                "score": record.get("sleepScore"),
            })

        if not sleep_records:
            return [TextContent(
                type="text",
                text=f"No sleep data found for the period {start_date_str} to {end_date_str}"
            )]

        # Format output
        lines.append(f"Found {len(sleep_records)} night(s) with sleep data:\n")

        for record in sleep_records:
            score_str = f"Score: {record['score']:.0f}/100" if record['score'] else "No score"

            lines.append(f"📅 Night of {record['date']}")
            lines.append(f"   ⏱️  {record['duration_str']} | ⭐ {score_str}\n")

        # Summary statistics
        total_records = len(sleep_records)
        avg_duration_seconds = sum(
            int(r["duration_str"].split("h")[0]) * 3600 +
            int(r["duration_str"].split("h")[1].split("m")[0]) * 60
            for r in sleep_records
        ) / total_records
        avg_hours = int(avg_duration_seconds // 3600)
        avg_mins = int((avg_duration_seconds % 3600) // 60)

        scores = [r["score"] for r in sleep_records if r["score"]]
        if scores:
            avg_score = sum(scores) / len(scores)
            lines.append(f"\n📊 Summary:")
            lines.append(f"   Average Duration: {avg_hours}h {avg_mins}m")
            lines.append(f"   Average Quality Score: {avg_score:.1f}/100")

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        print(f"Error fetching sleep data range: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure INTERVALS_API_KEY is configured."
        )]
