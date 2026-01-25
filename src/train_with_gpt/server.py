#!/usr/bin/env python3
"""MCP server for training analysis."""

import asyncio
import sys
import os
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .strava_client import StravaClient
from .config import config


def calculate_zone_distribution(stream_data: list, zone_boundaries: list) -> dict:
    """
    Calculate time spent in each zone.
    
    Args:
        stream_data: Array of HR or power values
        zone_boundaries: List of zone upper boundaries [z1_max, z2_max, z3_max, z4_max, z5_max]
    
    Returns:
        Dict with zone numbers as keys and seconds in each zone as values
    """
    if not stream_data or not zone_boundaries:
        return {}
    
    zone_time = {i+1: 0 for i in range(len(zone_boundaries) + 1)}
    
    for value in stream_data:
        if value is None:
            continue
        
        zone = len(zone_boundaries) + 1  # Default to highest zone
        for i, boundary in enumerate(zone_boundaries):
            if value <= boundary:
                zone = i + 1
                break
        
        zone_time[zone] += 1  # Each point represents 1 second typically
    
    return zone_time


app = Server("train-with-gpt")
strava = StravaClient()


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="connect_strava",
            description="Connect your Strava account to enable activity tracking. Opens a browser for authentication. Checks connection status first.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_last_week_activities",
            description="Fetches training activities from the last 7 days",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="analyze_activity",
            description="Performs detailed analysis of a specific activity using stream data. Shows zone distribution, detects intervals, and provides coaching insights.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {
                        "type": "number",
                        "description": "The Strava activity ID to analyze (from get_last_week_activities)",
                    },
                },
                "required": ["activity_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "connect_strava":
        try:
            # Reload config to pick up any changes
            config.load()
            strava.__init__()  # Reload strava client with new config
            
            # Check if already connected
            if strava.access_token:
                return [TextContent(
                    type="text",
                    text="✅ Already connected to Strava!\n\n"
                         "Your account is authenticated and ready to use.\n"
                         "You can now ask about your training activities."
                )]
            
            # Get credentials from config
            client_id = config.client_id
            client_secret = config.client_secret
            
            if not client_id or not client_secret:
                return [TextContent(
                    type="text",
                    text="🔑 Client credentials not configured!\n\n"
                         "**Setup Steps:**\n\n"
                         "1. Create Strava API application:\n"
                         "   → https://www.strava.com/settings/api\n"
                         "   → Set 'Authorization Callback Domain' to: localhost\n\n"
                         "2. Create config directory:\n"
                         "   mkdir -p ~/.config/train-with-gpt\n\n"
                         "3. Create config file:\n"
                         "   • Open: ~/.config/train-with-gpt/config.json\n"
                         "   • Add this content:\n\n"
                         "{\n"
                         '  "clientId": "YOUR_CLIENT_ID_HERE",\n'
                         '  "clientSecret": "YOUR_CLIENT_SECRET_HERE"\n'
                         "}\n\n"
                         "4. Say 'Connect my Strava account' again (no restart needed!)\n\n"
                         f"**Config path:** {config.get_config_path()}"
                )]
            
            data = await strava.connect()
            
            # Tokens are already saved by strava.connect()
            athlete = data.get('athlete', {})
            athlete_name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
            
            return [TextContent(
                type="text",
                text=f"✅ Successfully connected to Strava!\n\n"
                     f"Welcome, {athlete_name}! 🎉\n\n"
                     f"You can now ask me about your training activities."
            )]
            
        except Exception as e:
            print(f"Error connecting to Strava: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return [TextContent(
                type="text",
                text=f"❌ Error connecting to Strava: {str(e)}\n\n"
                     f"Please try again or check the server logs for details."
            )]
    
    elif name == "get_last_week_activities":
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
    
    elif name == "analyze_activity":
        try:
            # Handle both string and number inputs
            activity_id_raw = arguments.get("activity_id")
            activity_id = int(activity_id_raw) if activity_id_raw else None
            
            if not activity_id:
                return [TextContent(type="text", text="❌ Error: activity_id is required")]
            
            # Fetch zones
            zones_data = await strava.get_athlete_zones()
            
            # Fetch streams and laps
            streams = await strava.get_activity_streams(activity_id)
            laps = await strava.get_activity_laps(activity_id)
            
            # Build analysis report
            lines = [f"🔍 Detailed Analysis for Activity {activity_id}\n"]
            
            # Check what data we have
            has_hr = 'heartrate' in streams and streams['heartrate'].get('data')
            has_power = 'watts' in streams and streams['watts'].get('data')
            has_time = 'time' in streams and streams['time'].get('data')
            
            if not has_time:
                return [TextContent(type="text", text="❌ No time stream data available for this activity")]
            
            time_data = streams['time']['data']
            total_time = time_data[-1] if time_data else 0
            
            # Laps Analysis
            if laps and len(laps) > 1:  # More than 1 lap means intervals/structured workout
                lines.append("## 🏁 Laps / Intervals")
                lines.append("(Distance | Time | Pace/Speed | Heart Rate avg/max | Power | Cadence)\n")
                
                for i, lap in enumerate(laps, 1):
                    lap_stats = []
                    
                    # Distance
                    distance = lap.get('distance', 0) / 1000  # meters to km
                    if distance > 0:
                        lap_stats.append(f"{distance:.2f}km")
                    
                    # Time
                    elapsed = lap.get('elapsed_time', 0)
                    if elapsed > 0:
                        minutes = elapsed // 60
                        seconds = elapsed % 60
                        lap_stats.append(f"{minutes}m{seconds:02d}s")
                    
                    # Pace/Speed
                    avg_speed = lap.get('average_speed')
                    if avg_speed and distance > 0:
                        # Determine activity type - use 6.0 m/s (21.6 km/h) as threshold
                        if avg_speed < 6.0:  # Likely running
                            pace_min_per_km = (elapsed / 60) / distance
                            pace_min = int(pace_min_per_km)
                            pace_sec = int((pace_min_per_km - pace_min) * 60)
                            lap_stats.append(f"⏱️ {pace_min}:{pace_sec:02d}/km")
                        else:  # Likely cycling
                            speed_kmh = avg_speed * 3.6
                            lap_stats.append(f"⏱️ {speed_kmh:.1f}km/h")
                    
                    # Heart Rate
                    avg_hr = lap.get('average_heartrate')
                    max_hr = lap.get('max_heartrate')
                    if avg_hr:
                        if max_hr:
                            lap_stats.append(f"❤️ {avg_hr:.0f}/{max_hr:.0f} bpm")
                        else:
                            lap_stats.append(f"❤️ {avg_hr:.0f} bpm")
                    
                    # Power
                    avg_watts = lap.get('average_watts')
                    if avg_watts:
                        lap_stats.append(f"⚡ {avg_watts:.0f}W")
                    
                    # Cadence
                    avg_cadence = lap.get('average_cadence')
                    if avg_cadence:
                        # Check if running or cycling based on speed (6.0 m/s = ~21.6 km/h)
                        if avg_speed and avg_speed < 6.0:  # Running
                            cadence_value = avg_cadence * 2  # Strava returns strides/min
                            lap_stats.append(f"🔄 {cadence_value:.0f} spm")
                        else:  # Cycling
                            lap_stats.append(f"🔄 {avg_cadence:.0f} rpm")
                    
                    # Format lap line
                    lap_stats_str = " | ".join(lap_stats)
                    lines.append(f"  Lap {i}: {lap_stats_str}")
                
                lines.append("")
            elif laps and len(laps) == 1:
                lines.append("## ℹ️ Lap Information\n")
                lines.append("This activity has only one lap (no interval structure detected).\n")
            else:
                lines.append("## ℹ️ Lap Information\n")
                lines.append("No lap data available for this activity. The device may not have recorded laps.\n")
            
            # Heart Rate Analysis
            if has_hr and zones_data.get('heart_rate'):
                hr_data = streams['heartrate']['data']
                hr_zones = zones_data['heart_rate'].get('zones', [])
                
                lines.append("## ❤️ Heart Rate Zone Distribution\n")
                
                # Get zone boundaries
                if hr_zones:
                    zone_boundaries = [z.get('max', 0) for z in hr_zones[:-1]]  # Exclude last zone (no upper bound)
                    
                    # Calculate distribution
                    zone_dist = calculate_zone_distribution(hr_data, zone_boundaries)
                    
                    # Total time based on actual data points (streams are sampled, not every second)
                    total_points = sum(zone_dist.values())
                    
                    for zone_num in sorted(zone_dist.keys()):
                        time_in_zone = zone_dist[zone_num]
                        if time_in_zone > 0:
                            percent = (time_in_zone / total_points * 100) if total_points > 0 else 0
                            # Convert to actual time using the sampling rate
                            actual_seconds = int(time_in_zone * (total_time / len(hr_data)))
                            minutes = actual_seconds // 60
                            seconds = actual_seconds % 60
                            
                            # Get zone name and range
                            if zone_num <= len(hr_zones):
                                zone_info = hr_zones[zone_num - 1]
                                zone_min = zone_info.get('min', 0)
                                zone_max = zone_info.get('max', -1)
                                
                                # Handle highest zone (no upper bound)
                                if zone_max == -1:
                                    zone_range = f"{zone_min}+ bpm"
                                else:
                                    zone_range = f"{zone_min}-{zone_max} bpm"
                            else:
                                zone_range = "above zones"
                            
                            lines.append(f"  Zone {zone_num} ({zone_range}): {minutes}m{seconds:02d}s ({percent:.1f}%)")
                
                lines.append("")
            
            # Power Analysis (for cycling)
            if has_power and zones_data.get('power'):
                power_data = streams['watts']['data']
                power_zones = zones_data['power'].get('zones', [])
                
                lines.append("## ⚡ Power Analysis\n")
                
                if power_zones:
                    zone_boundaries = [z.get('max', 0) for z in power_zones[:-1]]
                    
                    zone_dist = calculate_zone_distribution(power_data, zone_boundaries)
                    
                    lines.append("**Zone Distribution:**")
                    for zone_num in sorted(zone_dist.keys()):
                        time_in_zone = zone_dist[zone_num]
                        if time_in_zone > 0:
                            percent = (time_in_zone / total_time * 100) if total_time > 0 else 0
                            minutes = time_in_zone // 60
                            seconds = time_in_zone % 60
                            
                            if zone_num <= len(power_zones):
                                zone_info = power_zones[zone_num - 1]
                                zone_min = zone_info.get('min', 0)
                                zone_max = zone_info.get('max', '∞')
                                zone_range = f"{zone_min}-{zone_max}W"
                            else:
                                zone_range = "above zones"
                            
                            lines.append(f"  Zone {zone_num} ({zone_range}): {minutes}m{seconds:02d}s ({percent:.1f}%)")
                
                lines.append("")
            
            return [TextContent(type="text", text="\n".join(lines))]
        
        except Exception as e:
            print(f"Error analyzing activity: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
    
    raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
