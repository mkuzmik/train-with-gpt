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
from .auth_flow import start_auth_flow
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
            
            data = await start_auth_flow(client_id, client_secret)
            
            # Save tokens
            access_token = data['access_token']
            refresh_token = data['refresh_token']
            expires_at = data.get('expires_at')
            
            config.save(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at
            )
            
            # Update current instance
            strava.access_token = access_token
            strava.refresh_token = refresh_token
            
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
                date_str = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00')).strftime('%Y-%m-%d')
                distance_km = activity.get('distance', 0) / 1000
                activity_type = activity.get('type', 'Unknown')
                name = activity.get('name', 'Untitled')
                lines.append(f"🏃 {name} ({activity_type}) - {distance_km:.2f}km on {date_str}")
            
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
