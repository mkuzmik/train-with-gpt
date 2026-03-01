"""Get last week activities tool."""

import sys
from datetime import datetime
from mcp.types import Tool, TextContent

from ..strava_client import StravaClient


def get_last_week_activities_tool() -> Tool:
    """Return the get_last_week_activities tool definition."""
    return Tool(
        name="get_last_week_activities",
        description="Fetches training activities from the last 7 days",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def get_last_week_activities_handler(arguments: dict, strava: StravaClient) -> list[TextContent]:
    """Handle get_last_week_activities tool calls."""
    try:
        activities = await strava.get_activities_last_week()
        
        if not activities:
            return [TextContent(type="text", text="No activities found in the last week.")]
        
        lines = [f"Found {len(activities)} activities from the last 7 days:\n"]
        
        for activity in activities:
            # Basic info
            date_str = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
            name = activity.get('name', 'Untitled')
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
            lines.append(f"\n📅 {date_str} - {activity_type}")
            lines.append(f"   {stats_str}")
            lines.append(f"   🔗 ID: {activity_id}")
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error fetching last week activities: {e}", file=sys.stderr)
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
