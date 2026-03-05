"""Get activities tool with flexible date filtering."""

import sys
from datetime import datetime, timedelta
from mcp.types import Tool, TextContent

from ..strava_client import StravaClient


def get_activities_tool() -> Tool:
    """Return the get_activities tool definition."""
    return Tool(
        name="get_activities",
        description=(
            "Fetches training activities with flexible date filtering. "
            "Can get activities from last week (default), a specific date, or a date range. "
            "Use get_current_date tool first if you're unsure about current date."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (inclusive). If omitted, defaults to 7 days ago.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (inclusive). If omitted, defaults to today.",
                },
            },
        },
    )


async def get_activities_handler(arguments: dict, strava: StravaClient) -> list[TextContent]:
    """Handle get_activities tool calls."""
    try:
        # Parse date arguments
        start_date_str = arguments.get("start_date")
        end_date_str = arguments.get("end_date")
        
        # Default: last 7 days
        now = datetime.now()
        if not start_date_str and not end_date_str:
            start_date = now - timedelta(days=7)
            end_date = now
            date_range_desc = "last 7 days"
        else:
            # Parse start date or default to 7 days ago
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                except ValueError:
                    return [TextContent(
                        type="text",
                        text=f"❌ Invalid start_date format: '{start_date_str}'. Use YYYY-MM-DD (e.g., 2024-01-15)"
                    )]
            else:
                start_date = now - timedelta(days=7)
            
            # Parse end date or default to now
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
                    # Set to end of day
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                except ValueError:
                    return [TextContent(
                        type="text",
                        text=f"❌ Invalid end_date format: '{end_date_str}'. Use YYYY-MM-DD (e.g., 2024-01-15)"
                    )]
            else:
                end_date = now
            
            # Validate date range
            if start_date > end_date:
                return [TextContent(
                    type="text",
                    text=f"❌ start_date ({start_date_str}) cannot be after end_date ({end_date_str})"
                )]
            
            # Build description
            if start_date_str == end_date_str:
                date_range_desc = f"{start_date_str}"
            else:
                date_range_desc = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        # Convert to epoch timestamps
        after_timestamp = int(start_date.timestamp())
        before_timestamp = int(end_date.timestamp())
        
        # Fetch activities
        activities = await strava.get_activities(
            after=after_timestamp,
            before=before_timestamp,
            per_page=200
        )
        
        if not activities:
            return [TextContent(type="text", text=f"No activities found for {date_range_desc}.")]
        
        lines = [f"Found {len(activities)} activities for {date_range_desc}:\n"]
        
        for activity in activities:
            # Basic info
            date_str = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
            activity_type = activity.get('sport_type') or activity.get('type', 'Unknown')
            
            # Performance metrics
            distance_km = activity.get('distance', 0) / 1000
            moving_time = activity.get('moving_time', 0)
            hours = moving_time // 3600
            minutes = (moving_time % 3600) // 60
            seconds = moving_time % 60
            
            # Build performance stats line
            stats = []
            
            # Distance & Time
            if distance_km > 0:
                stats.append(f"{distance_km:.2f}km")
            if moving_time > 0:
                if hours > 0:
                    stats.append(f"{hours}h{minutes:02d}m{seconds:02d}s")
                else:
                    stats.append(f"{minutes}m{seconds:02d}s")
            
            # Pace/Speed
            if distance_km > 0 and moving_time > 0:
                if activity_type in ['Run', 'Walk', 'Hike']:
                    pace_min_per_km = moving_time / 60 / distance_km
                    pace_min = int(pace_min_per_km)
                    pace_sec = int((pace_min_per_km - pace_min) * 60)
                    stats.append(f"⏱️ {pace_min}:{pace_sec:02d}/km")
                else:
                    avg_speed = activity.get('average_speed', 0) * 3.6  # m/s to km/h
                    stats.append(f"⏱️ {avg_speed:.1f}km/h")
            
            # Elevation
            elevation = activity.get('total_elevation_gain')
            if elevation and elevation > 0:
                stats.append(f"⛰️ {elevation:.0f}m")
            
            # Heart rate
            avg_hr = activity.get('average_heartrate')
            max_hr = activity.get('max_heartrate')
            if avg_hr:
                hr_str = f"❤️ {avg_hr:.0f}"
                if max_hr:
                    hr_str += f"/{max_hr:.0f}"
                hr_str += " bpm"
                stats.append(hr_str)
            
            # Power (for cycling)
            avg_watts = activity.get('average_watts')
            if avg_watts:
                stats.append(f"⚡ {avg_watts:.0f}W")
            
            # Cadence
            avg_cadence = activity.get('average_cadence')
            if avg_cadence:
                # Strava returns running cadence as strides/min, need to double for steps/min
                if activity_type in ['Run', 'Walk', 'Hike']:
                    cadence_value = avg_cadence * 2
                    stats.append(f"🔄 {cadence_value:.0f} spm")
                else:
                    stats.append(f"🔄 {avg_cadence:.0f} rpm")
            
            # Temperature
            avg_temp = activity.get('average_temp')
            if avg_temp is not None:
                stats.append(f"🌡️ {avg_temp}°C")
            
            # Format output
            activity_id = activity.get('id')
            stats_str = " | ".join(stats) if stats else "No stats"
            lines.append(f"\n📅 {date_str}")
            lines.append(f"   🏃 {activity_type}")
            lines.append(f"   {stats_str}")
            lines.append(f"   🔗 ID: {activity_id}")
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error fetching activities: {e}", file=sys.stderr)
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
