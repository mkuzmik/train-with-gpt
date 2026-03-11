"""Get HRV (Heart Rate Variability) data tool."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..garmin_client import GarminClient


def get_hrv_data_tool() -> Tool:
    """Return the get_hrv_data tool definition."""
    return Tool(
        name="get_hrv_data",
        description="Get Heart Rate Variability (HRV) data from Garmin Connect for a date range. HRV is a key recovery metric - higher values indicate better recovery. Returns nightly HRV averages and status.",
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


async def get_hrv_data_handler(arguments: dict, garmin: GarminClient) -> list[TextContent]:
    """Handle get_hrv_data tool calls."""
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
        
        # Fetch HRV data for each date
        lines = [f"HRV Data from {start_date_str} to {end_date_str}\n"]
        
        current_date = start_date
        hrv_records = []
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            
            try:
                hrv_data = await garmin.get_hrv_data(date_str)
                
                if hrv_data:
                    # HRV metrics
                    last_night_avg = hrv_data.get("lastNightAvg")
                    weekly_avg = hrv_data.get("weeklyAvg")
                    status = hrv_data.get("status")
                    
                    if last_night_avg is not None:
                        hrv_records.append({
                            "date": date_str,
                            "last_night_avg": last_night_avg,
                            "weekly_avg": weekly_avg,
                            "status": status,
                        })
            
            except Exception as e:
                print(f"[DEBUG] Error fetching HRV for {date_str}: {e}", file=sys.stderr)
            
            current_date += timedelta(days=1)
        
        if not hrv_records:
            return [TextContent(
                type="text",
                text=f"No HRV data found for the period {start_date_str} to {end_date_str}"
            )]
        
        # Format output
        lines.append(f"Found {len(hrv_records)} night(s) with HRV data:\n")
        
        for record in hrv_records:
            status_str = f"({record['status']})" if record['status'] else ""
            weekly_str = f"7-day avg: {record['weekly_avg']}ms" if record['weekly_avg'] else ""
            
            lines.append(f"📅 {record['date']}")
            lines.append(f"   💓 HRV: {record['last_night_avg']}ms {status_str}")
            if weekly_str:
                lines.append(f"   📊 {weekly_str}")
            lines.append("")
        
        # Summary statistics
        if hrv_records:
            avg_hrv = sum(r["last_night_avg"] for r in hrv_records) / len(hrv_records)
            min_hrv = min(r["last_night_avg"] for r in hrv_records)
            max_hrv = max(r["last_night_avg"] for r in hrv_records)
            
            lines.append(f"📊 Summary:")
            lines.append(f"   Average HRV: {avg_hrv:.1f}ms")
            lines.append(f"   Range: {min_hrv}ms - {max_hrv}ms")
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error fetching HRV data: {e}", file=sys.stderr)
        return [TextContent(
            type="text",
            text=f"❌ Error: {str(e)}\n\nMake sure you're connected to Garmin Connect."
        )]
