#!/usr/bin/env python3
"""MCP server for training analysis."""

import asyncio
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, Tool, TextContent

from .helpers import current_user_id
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
    self_test_tool,
    self_test_handler,
)
from .tools.self_test import SELF_TEST_PROMPT_NAME, self_test_prompt, self_test_prompt_result


app = Server("train-with-gpt")
intervals = IntervalsClient()

# One lock per user, shared by every StravaClient built for them, so
# concurrent requests don't race to refresh (and invalidate) the same
# rotating Strava refresh token. Single-process server, so asyncio is enough.
_strava_refresh_locks: dict[str, asyncio.Lock] = {}


def _get_active_data_client():
    """Resolve the data client for the current request (see data_client_for)."""
    return data_client_for(current_user_id())


def data_client_for(user_id: Optional[str]):
    """
    Resolve the data client for `user_id` (None: stdio/personal paths).

    HTTP/OAuth requests carry an access token this server's own OAuth
    Authorization Server issued (see oauth_provider.py); its `.subject` is
    the Strava athlete id it was issued for, and we look up that user's
    Strava credentials from store.py. Everything else (stdio, and the
    personal local-HTTP path) has no such token in context and keeps using
    the single personal `intervals` (IntervalsClient) instance, unchanged.
    """
    if not user_id:
        return intervals

    from . import store

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


def _get_wellness_client():
    """Resolve the wellness client for the current request (see wellness_client_for)."""
    return wellness_client_for(current_user_id())


def wellness_client_for(user_id: Optional[str]):
    """
    Resolve the client for sleep/HRV/resting-HR tools for `user_id`.

    OAuth'd users get an IntervalsClient on their own intervals.icu key if they
    added one at login (intervals_connect.py); otherwise their StravaClient,
    which the wellness handlers answer with NO_WELLNESS_DATA_MESSAGE.
    stdio/personal paths keep the personal `intervals` client.
    """
    if not user_id:
        return intervals

    from . import secret_box, store

    connection = store.get_intervals_connection(user_id)
    if connection and secret_box.is_configured():
        api_key = secret_box.decrypt(connection["encrypted_api_key"])
        if api_key:
            return IntervalsClient(api_key=api_key)
    return data_client_for(user_id)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    tools = [
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
        self_test_tool(),
    ]
    # For OAuth'd users the training repo is server configuration (the handler
    # refuses them), so don't offer the tool. The bearer token is in context
    # for tools/list too. Clients with a cached tool list still get the refusal.
    if current_user_id():
        tools = [tool for tool in tools if tool.name != "setup_training_repo"]
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "setup_training_repo":
        return await setup_training_repo_handler(arguments)
    elif name == "start_consultation":
        return await start_consultation_handler(arguments, _get_active_data_client(), _get_wellness_client())
    elif name == "get_current_date":
        return await get_current_date_handler(arguments)
    elif name == "get_activities":
        return await get_activities_handler(arguments, _get_active_data_client())
    elif name == "get_sleep_data":
        return await get_sleep_data_handler(arguments, _get_wellness_client())
    elif name == "get_hrv_data":
        return await get_hrv_data_handler(arguments, _get_wellness_client())
    elif name == "get_resting_heart_rate":
        return await get_resting_heart_rate_handler(arguments, _get_wellness_client())
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
    elif name == "self_test":
        return await self_test_handler(arguments)

    raise ValueError(f"Unknown tool: {name}")


@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [self_test_prompt()]


@app.get_prompt()
async def get_prompt(name: str, arguments: Optional[dict] = None) -> GetPromptResult:
    if name == SELF_TEST_PROMPT_NAME:
        return self_test_prompt_result()
    raise ValueError(f"Unknown prompt: {name}")


async def serve_stdio():
    """Run the MCP server over stdio until the client disconnects."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


def main():
    """Console-script entry point (`train-with-gpt`): run the stdio server."""
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
