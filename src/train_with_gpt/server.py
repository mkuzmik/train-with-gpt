#!/usr/bin/env python3
"""MCP server for training analysis."""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .strava_client import StravaClient
from .tools import (
    setup_training_repo_tool,
    setup_training_repo_handler,
    connect_strava_tool,
    connect_strava_handler,
    start_consultation_tool,
    start_consultation_handler,
    get_activities_tool,
    get_activities_handler,
    get_current_date_tool,
    get_current_date_handler,
    analyze_activity_tool,
    analyze_activity_handler,
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
)


app = Server("train-with-gpt")
strava = StravaClient()



@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        connect_strava_tool(),
        start_consultation_tool(),
        get_current_date_tool(),
        get_activities_tool(),
        analyze_activity_tool(),
        setup_training_repo_tool(),
        discuss_goals_tool(),
        save_goals_tool(),
        read_goals_tool(),
        save_consultation_notes_tool(),
        read_consultation_notes_tool(),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "connect_strava":
        return await connect_strava_handler(arguments, strava)
    elif name == "setup_training_repo":
        return await setup_training_repo_handler(arguments)
    elif name == "start_consultation":
        return await start_consultation_handler(arguments)
    elif name == "get_current_date":
        return await get_current_date_handler(arguments)
    elif name == "get_activities":
        return await get_activities_handler(arguments, strava)
    elif name == "analyze_activity":
        return await analyze_activity_handler(arguments, strava)
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
