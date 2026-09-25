#!/usr/bin/env python3
"""MCP server for training analysis."""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .intervals_client import IntervalsClient
from .strava_client import StravaClient
from .tools import (
    setup_training_repo_tool,
    setup_training_repo_handler,
    start_consultation_tool,
    start_consultation_handler,
    get_activities_tool,
    get_activities_handler,
    get_current_date_tool,
    get_current_date_handler,
    get_sleep_data_tool,
    get_sleep_data_handler,
    get_hrv_data_tool,
    get_hrv_data_handler,
    get_resting_heart_rate_tool,
    get_resting_heart_rate_handler,
    analyze_activity_tool,
    analyze_activity_handler,
    analyze_lap_tool,
    analyze_lap_handler,
    discuss_goals_tool,
    discuss_goals_handler,
    save_goals_tool,
    save_goals_handler,
    read_goals_tool,
    read_goals_handler,
    save_consultation_notes_tool,
    save_consultation_notes_handler,
    read_consultation_notes_tool,
    read_consultation_notes_handler,
    list_consultation_notes_tool,
    list_consultation_notes_handler,
    search_consultation_notes_tool,
    search_consultation_notes_handler,
)


app = Server("train-with-gpt")
intervals = IntervalsClient()

# One lock per user, shared by every StravaClient built for them, so
# concurrent requests don't race to refresh (and invalidate) the same
# rotating Strava refresh token. Single-process server, so asyncio is enough.
_strava_refresh_locks: dict[str, asyncio.Lock] = {}


def _get_active_data_client():
    """
    Resolve the data client for the current request.

    HTTP/OAuth requests carry an access token this server's own OAuth
    Authorization Server issued (see oauth_provider.py); its `.subject` is
    the Strava athlete id it was issued for, and we look up that user's
    Strava credentials from store.py. Everything else (stdio, and the
    personal local-HTTP path) has no such token in context and keeps using
    the single personal `intervals` (IntervalsClient) instance, unchanged.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token

    access_token = get_access_token()
    if not access_token or not access_token.subject:
        return intervals

    from . import store

    user_id = access_token.subject
    user = store.get_user(user_id)
    if not user:
        raise ValueError(f"No stored Strava credentials for user {user_id}")

    async def on_refresh(new_access_token, new_refresh_token, new_expires_at):
        store.update_user_tokens(user_id, new_access_token, new_refresh_token, new_expires_at)

    def load_stored_tokens():
        row = store.get_user(user_id)
        return (row["access_token"], row["refresh_token"], row["token_expires_at"]) if row else None

    return StravaClient(
        access_token=user["access_token"],
        refresh_token=user["refresh_token"],
        expires_at=user["token_expires_at"],
        on_refresh=on_refresh,
        refresh_lock=_strava_refresh_locks.setdefault(user_id, asyncio.Lock()),
        load_stored_tokens=load_stored_tokens,
    )


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        start_consultation_tool(),
        get_current_date_tool(),
        get_activities_tool(),
        get_sleep_data_tool(),
        get_hrv_data_tool(),
        get_resting_heart_rate_tool(),
        analyze_activity_tool(),
        analyze_lap_tool(),
        setup_training_repo_tool(),
        discuss_goals_tool(),
        save_goals_tool(),
        read_goals_tool(),
        save_consultation_notes_tool(),
        read_consultation_notes_tool(),
        list_consultation_notes_tool(),
        search_consultation_notes_tool(),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "setup_training_repo":
        return await setup_training_repo_handler(arguments)
    elif name == "start_consultation":
        return await start_consultation_handler(arguments)
    elif name == "get_current_date":
        return await get_current_date_handler(arguments)
    elif name == "get_activities":
        return await get_activities_handler(arguments, _get_active_data_client())
    elif name == "get_sleep_data":
        return await get_sleep_data_handler(arguments, _get_active_data_client())
    elif name == "get_hrv_data":
        return await get_hrv_data_handler(arguments, _get_active_data_client())
    elif name == "get_resting_heart_rate":
        return await get_resting_heart_rate_handler(arguments, _get_active_data_client())
    elif name == "analyze_activity":
        return await analyze_activity_handler(arguments, _get_active_data_client())
    elif name == "analyze_lap":
        return await analyze_lap_handler(arguments, _get_active_data_client())
    elif name == "discuss_goals":
        return await discuss_goals_handler(arguments)
    elif name == "save_goals":
        return await save_goals_handler(arguments)
    elif name == "read_goals":
        return await read_goals_handler(arguments)
    elif name == "save_consultation_notes":
        return await save_consultation_notes_handler(arguments)
    elif name == "read_consultation_notes":
        return await read_consultation_notes_handler(arguments)
    elif name == "list_consultation_notes":
        return await list_consultation_notes_handler(arguments)
    elif name == "search_consultation_notes":
        return await search_consultation_notes_handler(arguments)

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
