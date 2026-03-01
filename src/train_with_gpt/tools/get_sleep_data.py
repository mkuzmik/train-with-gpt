"""Get sleep data range tool."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..garmin_client import GarminClient


def get_sleep_data_tool() -> Tool:
    """Return the get_sleep_data tool definition."""
    return Tool(
        name="get_sleep_data",
        description="Get sleep data from Garmin Connect for a date range (or single date if start=end). Returns sleep quality, duration, and stages for each night. Useful for analyzing sleep patterns and trends.",
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


async def get_sleep_data_handler(arguments: dict, garmin: GarminClient) -> list[TextContent]:
    """Handle get_sleep_data_range tool calls."""
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
        
        # Fetch sleep data for each date
        lines = [f"Sleep Data from {start_date_str} to {end_date_str}\n"]
        
        current_date = start_date
        sleep_records = []
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            
            try:
                sleep_data = await garmin.get_sleep_data(date_str)
                
                if sleep_data:
                    daily_values = sleep_data.get("dailySleepDTO", {})
                    
                    # Sleep times
                    sleep_start = daily_values.get("sleepStartTimestampGMT")
                    sleep_end = daily_values.get("sleepEndTimestampGMT")
                    
                    if sleep_start and sleep_end:
                        start_dt = datetime.fromtimestamp(sleep_start / 1000)
                        end_dt = datetime.fromtimestamp(sleep_end / 1000)
                        
                        # Duration
                        total_seconds = daily_values.get("sleepTimeSeconds", 0)
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        
                        # Sleep quality
                        sleep_scores = sleep_data.get("sleepScores", {})
                        overall_score = sleep_scores.get("overall", {}).get("value")
                        
                        # Store record
                        sleep_records.append({
                            "date": date_str,
                            "start_dt": start_dt,
                            "end_dt": end_dt,
                            "duration_str": f"{hours}h {minutes}m",
                            "score": overall_score,
                        })
            
            except Exception as e:
                print(f"[DEBUG] Error fetching sleep for {date_str}: {e}", file=sys.stderr)
            
            current_date += timedelta(days=1)
        
        if not sleep_records:
            return [TextContent(
                type="text",
                text=f"No sleep data found for the period {start_date_str} to {end_date_str}"
            )]
        
        # Format output
        lines.append(f"Found {len(sleep_records)} night(s) with sleep data:\n")
        
        for record in sleep_records:
            start_date_part = record["start_dt"].strftime("%Y-%m-%d")
            end_date_part = record["end_dt"].strftime("%Y-%m-%d")
            start_time = record["start_dt"].strftime("%H:%M")
            end_time = record["end_dt"].strftime("%H:%M")
            
            if start_date_part == end_date_part:
                date_info = f"{start_date_part}"
            else:
                date_info = f"{start_date_part} to {end_date_part}"
            
            score_str = f"Score: {record['score']}/100" if record['score'] else "No score"
            
            lines.append(f"📅 Night of {record['start_dt'].strftime('%Y-%m-%d')} ({start_time} - {end_time})")
            lines.append(f"   ⏱️  {record['duration_str']} | ⭐ {score_str}\n")
        
        # Summary statistics
        if sleep_records:
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
            text=f"❌ Error: {str(e)}\n\nMake sure you're connected to Garmin Connect."
        )]
