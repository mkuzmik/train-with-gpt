#!/usr/bin/env python3
"""Test script for train-with-gpt MCP server."""

import asyncio
import sys
import json
from train_with_gpt.server import call_tool, list_tools


async def test_tool(tool_name: str, arguments: dict = None):
    """Test any MCP tool."""
    if arguments is None:
        arguments = {}
    
    print(f"Testing {tool_name}...")
    print("-" * 50)
    
    try:
        result = await call_tool(tool_name, arguments)
        for content in result:
            print(content.text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


async def show_help():
    """Display help with available tools."""
    print("Usage:")
    print("  python test_tools.py <tool_name> [arguments_json]")
    print("")
    print("Available tools:")
    
    tools = await list_tools()
    for tool in tools:
        print(f"  • {tool.name}")
        print(f"    {tool.description}")
    
    print("")
    print("Examples:")
    print("  python test_tools.py get_current_date")
    print("  python test_tools.py get_activities")
    print("  python test_tools.py get_activities '{\"start_date\": \"2024-01-15\", \"end_date\": \"2024-01-20\"}'")
    print("  python test_tools.py connect_strava")
    print('  python test_tools.py some_tool \'{"arg1": "value1"}\'')


async def main():
    """Run tool test based on arguments."""
    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h", "help"]:
        await show_help()
        sys.exit(0 if len(sys.argv) >= 2 else 1)
    
    tool_name = sys.argv[1]
    
    # Parse arguments if provided
    arguments = {}
    if len(sys.argv) > 2:
        try:
            arguments = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON arguments: {sys.argv[2]}")
            sys.exit(1)
    
    await test_tool(tool_name, arguments)


if __name__ == "__main__":
    asyncio.run(main())
