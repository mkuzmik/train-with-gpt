"""Get resting heart rate data tool."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..garmin_client import GarminClient


def get_resting_heart_rate_tool() -> Tool:
    """Return the get_resting_heart_rate tool definition."""
    return Tool(
        name="get_resting_heart_rate",
        description="Get resting heart rate (RHR) data from Garmin Connect for a date range. RHR is a key recovery and fitness metric - lower values generally indicate better fitness, elevated values may indicate overtraining or illness.",
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


async def get_resting_heart_rate_handler(arguments: dict, garmin: GarminClient) -> list[TextContent]:
    """Handle get_resting_heart_rate tool calls."""
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
        
        # Fetch resting heart rate data for each date
        lines = [f"Resting Heart Rate from {start_date_str} to {end_date_str}\n"]
        
        current_date = start_date
        rhr_records = []
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            
            try:
                hr_data = await garmin.get_heart_rates(date_str)
                
                if hr_data:
                    # Get resting heart rate
                    resting_hr = hr_data.get("restingHeartRate")
                    
                    if resting_hr is not None:
                        rhr_records.append({
                            "date": date_str,
                            "resting_hr": resting_hr,
                        })
            
            except Exception as e:
                print(f"[DEBUG] Error fetching RHR for {date_str}: {e}", file=sys.stderr)
            
            current_date += timedelta(days=1)
        
        if not rhr_records:
            return [TextContent(
                type="text",
                text=f"No resting heart rate data found for the period {start_date_str} to {end_date_str}"
            )]
        
        # Format output
        lines.append(f"Found {len(rhr_records)} day(s) with RHR data:\n")
        
        for record in rhr_records:
            lines.append(f"📅 {record['date']}")
            lines.append(f"   ❤️  RHR: {record['resting_hr']} bpm\n")
        
        # Summary statistics
        if rhr_records:
            avg_rhr = sum(r["resting_hr"] for r in rhr_records) / len(rhr_records)
            min_rhr = min(r["resting_hr"] for r in rhr_records)
            max_rhr = max(r["resting_hr"] for r in rhr_records)
            
            lines.append(f"📊 Summary:")
            lines.append(f"   Average RHR: {avg_rhr:.1f} bpm")
            lines.append(f"   Range: {min_rhr} - {max_rhr} bpm")
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error fetching resting heart rate data: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure you're connected to Garmin Connect."
        )]
