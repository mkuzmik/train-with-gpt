"""Get sleep data tool."""

import sys
from datetime import datetime
from mcp.types import Tool, TextContent

from ..garmin_client import GarminClient


def get_sleep_data_tool() -> Tool:
    """Return the get_sleep_data tool definition."""
    return Tool(
        name="get_sleep_data",
        description="Get sleep data from Garmin Connect for a specific date. Shows sleep stages, duration, quality score, and more.",
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (e.g., '2024-01-15'). Defaults to today if not specified.",
                },
            },
        },
    )


async def get_sleep_data_handler(arguments: dict, garmin: GarminClient) -> list[TextContent]:
    """Handle get_sleep_data tool calls."""
    try:
        # Get date (default to today)
        date_str = arguments.get("date")
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Validate date format
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return [TextContent(
                type="text",
                text=f"❌ Invalid date format: '{date_str}'. Use YYYY-MM-DD (e.g., 2024-01-15)"
            )]
        
        # Fetch sleep data
        sleep_data = await garmin.get_sleep_data(date_str)
        
        if not sleep_data:
            return [TextContent(
                type="text",
                text=f"No sleep data found for {date_str}"
            )]
        
        # Format sleep data
        lines = [f"🌙 Sleep Data for {date_str}\n"]
        
        # Daily sleep values
        daily_values = sleep_data.get("dailySleepDTO", {})
        
        # Sleep times
        sleep_start = daily_values.get("sleepStartTimestampGMT")
        sleep_end = daily_values.get("sleepEndTimestampGMT")
        
        if sleep_start and sleep_end:
            start_time = datetime.fromtimestamp(sleep_start / 1000).strftime("%H:%M")
            end_time = datetime.fromtimestamp(sleep_end / 1000).strftime("%H:%M")
            lines.append(f"⏰ Sleep Window: {start_time} - {end_time}")
        
        # Sleep duration
        total_seconds = daily_values.get("sleepTimeSeconds", 0)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        lines.append(f"⏱️  Total Sleep: {hours}h {minutes}m")
        
        # Sleep quality
        sleep_scores = sleep_data.get("sleepScores", {})
        overall_score = sleep_scores.get("overall", {}).get("value")
        if overall_score:
            lines.append(f"⭐ Sleep Score: {overall_score}/100")
        
        # Sleep stages
        lines.append(f"\n📊 Sleep Stages:")
        
        deep_seconds = daily_values.get("deepSleepSeconds", 0)
        if deep_seconds:
            deep_mins = deep_seconds // 60
            lines.append(f"   💤 Deep Sleep: {deep_mins} min")
        
        light_seconds = daily_values.get("lightSleepSeconds", 0)
        if light_seconds:
            light_mins = light_seconds // 60
            lines.append(f"   🌙 Light Sleep: {light_mins} min")
        
        rem_seconds = daily_values.get("remSleepSeconds", 0)
        if rem_seconds:
            rem_mins = rem_seconds // 60
            lines.append(f"   🧠 REM Sleep: {rem_mins} min")
        
        awake_seconds = daily_values.get("awakeSleepSeconds", 0)
        if awake_seconds:
            awake_mins = awake_seconds // 60
            lines.append(f"   👁️  Awake: {awake_mins} min")
        
        # Additional metrics
        restless_moments = daily_values.get("restlessMomentCount")
        if restless_moments:
            lines.append(f"\n🔄 Restless Moments: {restless_moments}")
        
        avg_spo2 = daily_values.get("avgSpo2Value")
        if avg_spo2:
            lines.append(f"🫁 Avg SpO2: {avg_spo2}%")
        
        avg_respiration = daily_values.get("avgRespirationValue")
        if avg_respiration:
            lines.append(f"🌬️  Avg Respiration: {avg_respiration} breaths/min")
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error fetching sleep data: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure you're connected to Garmin Connect (use connect_garmin)."
        )]
