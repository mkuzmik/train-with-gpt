"""Connect Strava tool."""

import sys
from mcp.types import Tool, TextContent

from ..strava_client import StravaClient
from ..config import config


def connect_strava_tool() -> Tool:
    """Return the connect_strava tool definition."""
    return Tool(
        name="connect_strava",
        description="Connect your Strava account to enable activity tracking. Opens a browser for authentication. Checks connection status first.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def connect_strava_handler(arguments: dict, strava: StravaClient) -> list[TextContent]:
    """Handle connect_strava tool calls."""
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
