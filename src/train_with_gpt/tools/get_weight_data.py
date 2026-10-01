"""Get body weight history tool."""

import sys
from datetime import datetime
from mcp.types import Tool, TextContent

from ..helpers import NO_WELLNESS_DATA_MESSAGE
from ..strava_client import StravaClient

# Weight moves slowly, so allow a much longer window than the daily recovery
# metrics: a full year covers a season or a build-up.
MAX_RANGE_DAYS = 366
MODES = ("datapoints", "summary")


def get_weight_data_tool() -> Tool:
    """Return the get_weight_data tool definition."""
    return Tool(
        name="get_weight_data",
        description=(
            "Get body weight history (kg) from intervals.icu wellness data for a date range "
            f"(up to {MAX_RANGE_DAYS} days). mode='datapoints' (default) lists every logged weigh-in "
            "followed by summary statistics; mode='summary' returns only the statistics (average, "
            "min/max, change from first to last weigh-in) - use it for long ranges or when only "
            "the average weight over a period is needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Required.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Required.",
                },
                "mode": {
                    "type": "string",
                    "enum": list(MODES),
                    "description": "'datapoints' (default): every weigh-in plus a summary. 'summary': statistics only.",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )


def _format_kg(value: float) -> str:
    return f"{value:.1f} kg"


async def get_weight_data_handler(arguments: dict, intervals) -> list[TextContent]:
    """Handle get_weight_data tool calls."""
    try:
        if isinstance(intervals, StravaClient):
            return [TextContent(type="text", text=NO_WELLNESS_DATA_MESSAGE)]

        start_date_str = arguments.get("start_date")
        end_date_str = arguments.get("end_date")
        # Only a missing (or null) mode means the default; any other value must be valid.
        mode = arguments.get("mode")
        if mode is None:
            mode = "datapoints"

        if not start_date_str or not end_date_str:
            return [TextContent(
                type="text",
                text="❌ Both start_date and end_date are required"
            )]

        if mode not in MODES:
            return [TextContent(
                type="text",
                text=f"❌ Invalid mode '{mode}'. Use 'datapoints' or 'summary'."
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

        # Both ends are inclusive, so count calendar days, not the difference.
        days = (end_date - start_date).days + 1
        if days > MAX_RANGE_DAYS:
            return [TextContent(
                type="text",
                text=f"❌ Date range too large ({days} days). Maximum is {MAX_RANGE_DAYS} days."
            )]

        wellness_records = await intervals.get_wellness(start_date_str, end_date_str)

        weight_records = []
        for record in wellness_records:
            weight = record.get("weight")
            if weight is None:
                continue
            weight_records.append({
                "date": record.get("id"),
                "weight": weight,
            })
        weight_records.sort(key=lambda r: r["date"] or "")

        if not weight_records:
            return [TextContent(
                type="text",
                text=f"No weight data found for the period {start_date_str} to {end_date_str}"
            )]

        lines = [f"Body Weight from {start_date_str} to {end_date_str}\n"]
        lines.append(f"Found {len(weight_records)} day(s) with weight data:\n")

        if mode == "datapoints":
            for record in weight_records:
                lines.append(f"📅 {record['date']}: ⚖️  {_format_kg(record['weight'])}")
            lines.append("")

        # Summary statistics
        weights = [r["weight"] for r in weight_records]
        first, last = weight_records[0], weight_records[-1]
        change = last["weight"] - first["weight"]

        lines.append("📊 Summary:")
        lines.append(f"   Average weight: {_format_kg(sum(weights) / len(weights))}")
        lines.append(f"   Range: {_format_kg(min(weights))} - {_format_kg(max(weights))}")
        lines.append(
            f"   Change: {change:+.1f} kg "
            f"({_format_kg(first['weight'])} on {first['date']} → {_format_kg(last['weight'])} on {last['date']})"
        )

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        print(f"Error fetching weight data: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure INTERVALS_API_KEY is configured."
        )]
