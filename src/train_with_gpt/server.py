#!/usr/bin/env python3
"""A simple MCP server that provides basic tools and resources."""

import asyncio
import sys
import os
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .strava_client import StravaClient
from .config import config


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
                    stats.append(f"🔄 {avg_cadence:.0f} rpm")
                
                # Temperature
                avg_temp = activity.get('average_temp')
                if avg_temp is not None:
                    stats.append(f"🌡️ {avg_temp}°C")
                
                # Format output
                stats_str = " | ".join(stats) if stats else "No stats"
                lines.append(f"\n📅 {date_str}")
                lines.append(f"🏃 {name} ({activity_type})")
                lines.append(f"   {stats_str}")
            
            return [TextContent(type="text", text="\n".join(lines))]
        
        except Exception as e:
            print(f"Error fetching last week activities: {e}", file=sys.stderr)
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
