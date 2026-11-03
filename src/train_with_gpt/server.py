#!/usr/bin/env python3
"""MCP server for training analysis."""

import asyncio
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, Tool, TextContent

from .activity_source import (
    ACTIVITY_TOOLS,
    DEFAULT_SOURCE,
    INTERVALS_ICU,
    INTERVALS_NOT_CONNECTED_MESSAGE,
    INTERVALS_NOT_OFFERED_MESSAGE,
    STRAVA,
    invalid_source_message,
    with_source_param,
)
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
    get_weight_data_tool,
    get_weight_data_handler,
    analyze_activity_tool,
    analyze_activity_handler,
    analyze_lap_tool,
    analyze_lap_handler,
    save_goals_tool,
    save_goals_handler,
    read_goals_tool,
    read_goals_handler,
    save_athlete_profile_tool,
    save_athlete_profile_handler,
    read_athlete_profile_tool,
    read_athlete_profile_handler,
    build_athlete_profile_tool,
    build_athlete_profile_handler,
    get_training_science_tool,
    get_training_science_handler,
    save_consultation_notes_tool,
    save_consultation_notes_handler,
    read_consultation_notes_tool,
    read_consultation_notes_handler,
    list_consultation_notes_tool,
    list_consultation_notes_handler,
    search_consultation_notes_tool,
    search_consultation_notes_handler,
    read_memory_index_tool,
    read_memory_index_handler,
    read_memory_tool,
    read_memory_handler,
    save_memory_tool,
    save_memory_handler,
    update_memory_tool,
    update_memory_handler,
    delete_memory_tool,
    delete_memory_handler,
    build_memory_from_notes_tool,
    build_memory_from_notes_handler,
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
    Resolve the client for sleep/HRV/resting-HR/weight tools for `user_id`.

    OAuth'd users get an IntervalsClient on their own intervals.icu key if they
    added one at login (intervals_connect.py); otherwise their StravaClient,
    which the wellness handlers answer with NO_WELLNESS_DATA_MESSAGE.
    stdio/personal paths keep the personal `intervals` client.
    """
    if not user_id:
        return intervals
    return intervals_client_for(user_id) or data_client_for(user_id)


def intervals_client_for(user_id: str) -> Optional[IntervalsClient]:
    """An OAuth'd user's own intervals.icu client, or None if they didn't connect one."""
    from . import secret_box, store

    connection = store.get_intervals_connection(user_id)
    if connection and secret_box.is_configured():
        api_key = secret_box.decrypt(connection["encrypted_api_key"])
        if api_key:
            return IntervalsClient(api_key=api_key)
    return None


def _activity_client(arguments: dict):
    """
    The client for get_activities/analyze_activity/analyze_lap, or an error text.

    Hosted users pick it with `source` (Strava by default, see
    activity_source.py); stdio/personal paths always use intervals.icu.
    """
    user_id = current_user_id()
    if not user_id:
        return intervals, None

    # Only a missing (or null) source means the default; any other value must be valid.
    source = arguments.get("source")
    if source is None:
        source = DEFAULT_SOURCE
    if source == STRAVA:
        return data_client_for(user_id), None
    if source != INTERVALS_ICU:
        return None, invalid_source_message(source)

    from . import secret_box

    client = intervals_client_for(user_id)
    if client:
        return client, None
    if not secret_box.is_configured():
        return None, INTERVALS_NOT_OFFERED_MESSAGE
    return None, INTERVALS_NOT_CONNECTED_MESSAGE


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
        get_weight_data_tool(),
        analyze_activity_tool(),
        analyze_lap_tool(),
        setup_training_repo_tool(),
        save_goals_tool(),
        read_goals_tool(),
        build_athlete_profile_tool(),
        get_training_science_tool(),
        read_athlete_profile_tool(),
        save_athlete_profile_tool(),
        save_consultation_notes_tool(),
        read_consultation_notes_tool(),
        list_consultation_notes_tool(),
        search_consultation_notes_tool(),
        read_memory_index_tool(),
        read_memory_tool(),
        save_memory_tool(),
        update_memory_tool(),
        delete_memory_tool(),
        build_memory_from_notes_tool(),
        self_test_tool(),
    ]
    # For OAuth'd users the training repo is server configuration (the handler
    # refuses them), so don't offer the tool. The bearer token is in context
    # for tools/list too. Clients with a cached tool list still get the refusal.
    if current_user_id():
        tools = [tool for tool in tools if tool.name != "setup_training_repo"]
        # Hosted users choose where activities come from (activity_source.py).
        tools = [with_source_param(tool) if tool.name in ACTIVITY_TOOLS else tool for tool in tools]
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name in ACTIVITY_TOOLS:
        client, error = _activity_client(arguments)
        if error:
            return [TextContent(type="text", text=error)]
        if name == "get_activities":
            return await get_activities_handler(arguments, client)
        if name == "analyze_activity":
            return await analyze_activity_handler(arguments, client)
        return await analyze_lap_handler(arguments, client)

    if name == "setup_training_repo":
        return await setup_training_repo_handler(arguments)
    elif name == "start_consultation":
        return await start_consultation_handler(arguments, _get_active_data_client(), _get_wellness_client())
    elif name == "get_current_date":
        return await get_current_date_handler(arguments)
    elif name == "get_sleep_data":
        return await get_sleep_data_handler(arguments, _get_wellness_client())
    elif name == "get_hrv_data":
        return await get_hrv_data_handler(arguments, _get_wellness_client())
    elif name == "get_resting_heart_rate":
        return await get_resting_heart_rate_handler(arguments, _get_wellness_client())
    elif name == "get_weight_data":
        return await get_weight_data_handler(arguments, _get_wellness_client())
    elif name == "save_goals":
        return await save_goals_handler(arguments)
    elif name == "read_goals":
        return await read_goals_handler(arguments)
    elif name == "build_athlete_profile":
        return await build_athlete_profile_handler(arguments)
    elif name == "get_training_science":
        return await get_training_science_handler(arguments)
    elif name == "read_athlete_profile":
        return await read_athlete_profile_handler(arguments)
    elif name == "save_athlete_profile":
        return await save_athlete_profile_handler(arguments)
    elif name == "save_consultation_notes":
        return await save_consultation_notes_handler(arguments)
    elif name == "read_consultation_notes":
        return await read_consultation_notes_handler(arguments)
    elif name == "list_consultation_notes":
        return await list_consultation_notes_handler(arguments)
    elif name == "search_consultation_notes":
        return await search_consultation_notes_handler(arguments)
    elif name == "read_memory_index":
        return await read_memory_index_handler(arguments)
    elif name == "read_memory":
        return await read_memory_handler(arguments)
    elif name == "save_memory":
        return await save_memory_handler(arguments)
    elif name == "update_memory":
        return await update_memory_handler(arguments)
    elif name == "delete_memory":
        return await delete_memory_handler(arguments)
    elif name == "build_memory_from_notes":
        return await build_memory_from_notes_handler(arguments)
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
