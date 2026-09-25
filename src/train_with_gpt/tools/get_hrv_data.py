"""Get HRV (Heart Rate Variability) data tool."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..helpers import NO_WELLNESS_DATA_MESSAGE
from ..strava_client import StravaClient


def get_hrv_data_tool() -> Tool:
    """Return the get_hrv_data tool definition."""
    return Tool(
        name="get_hrv_data",
        description="Get Heart Rate Variability (HRV) data from intervals.icu for a date range. HRV is a key recovery metric - higher values indicate better recovery. Returns nightly HRV values and rolling averages.",
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
            },
            "required": ["start_date", "end_date"],
        },
    )


async def get_hrv_data_handler(arguments: dict, intervals) -> list[TextContent]:
    """Handle get_hrv_data tool calls."""
    try:
        if isinstance(intervals, StravaClient):
            return [TextContent(type="text", text=NO_WELLNESS_DATA_MESSAGE)]

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

        lines = [f"HRV Data from {start_date_str} to {end_date_str}\n"]

        wellness_records = await intervals.get_wellness(start_date_str, end_date_str)

        hrv_records = []
        for record in wellness_records:
            hrv = record.get("hrv")
            if hrv is None:
                continue
            hrv_records.append({
                "date": record.get("id"),
                "hrv": hrv,
            })

        if not hrv_records:
            return [TextContent(
                type="text",
                text=f"No HRV data found for the period {start_date_str} to {end_date_str}"
            )]

        # Format output (most recent first, matching prior tool behavior)
        hrv_records.sort(key=lambda r: r["date"], reverse=True)

        lines.append(f"Found {len(hrv_records)} night(s) with HRV data:\n")

        for record in hrv_records:
            lines.append(f"📅 {record['date']}")
            lines.append(f"   💓 HRV: {record['hrv']:.0f}ms")
            lines.append("")

        # Summary statistics with rolling averages
        period_avg = sum(r["hrv"] for r in hrv_records) / len(hrv_records)
        min_hrv = min(r["hrv"] for r in hrv_records)
        max_hrv = max(r["hrv"] for r in hrv_records)

        lines.append(f"📊 Summary:")
        lines.append(f"   Period Average: {period_avg:.1f}ms ({len(hrv_records)} days)")
        lines.append(f"   Range: {min_hrv:.0f}ms - {max_hrv:.0f}ms")

        if len(hrv_records) >= 7:
            last_7_days = hrv_records[:7]  # Most recent 7 days
            avg_7d = sum(r["hrv"] for r in last_7_days) / len(last_7_days)
            lines.append(f"   7-day Rolling Avg: {avg_7d:.1f}ms")

        if len(hrv_records) >= 14:
            last_14_days = hrv_records[:14]  # Most recent 14 days
            avg_14d = sum(r["hrv"] for r in last_14_days) / len(last_14_days)
            lines.append(f"   14-day Rolling Avg: {avg_14d:.1f}ms")

        if len(hrv_records) >= 28:
            last_28_days = hrv_records[:28]  # Most recent 28 days (4 weeks)
            avg_28d = sum(r["hrv"] for r in last_28_days) / len(last_28_days)
            lines.append(f"   28-day Rolling Avg: {avg_28d:.1f}ms")

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        print(f"Error fetching HRV data: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure INTERVALS_API_KEY is configured."
        )]
